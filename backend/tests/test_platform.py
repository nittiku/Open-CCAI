import json
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.main import app
from app.db import Session, engine
from app.models import *
from app.runtime import execute_step, snapshot_step, compute
from app import providers
from app.providers import ProviderError, Reply
from app.flows import validate_flow
from app.knowledge import retrieve, ingest
from app.tools import call_tool, UncertainOutcome
from app.security import decrypt

API = "/api/v1"


def bot(admin, origins=None):
    r = admin.post(
        API + "/bots",
        json={"name": "Support", "origins": origins or ["https://shop.example"]},
    )
    assert r.status_code == 200, r.text
    return r.json()


def flow(nodes, edges, entry="welcome"):
    return {
        "schema_version": 1,
        "entry": entry,
        "nodes": [
            {"id": nid, "type": kind, "config": cfg, "position": {"x": i * 250, "y": 0}}
            for i, (nid, kind, cfg) in enumerate(nodes)
        ],
        "edges": [
            {"id": str(i), "source": s, "label": b, "target": t}
            for i, (s, b, t) in enumerate(edges)
        ],
    }


def publish(admin, b, definition=None):
    if definition:
        r = admin.put(API + f"/bots/{b['id']}/draft", json={"flow": definition})
        assert r.status_code == 200, r.text
        assert not r.json()["errors"], r.text
    r = admin.post(API + f"/bots/{b['id']}/publish")
    assert r.status_code == 200, r.text
    return r.json()


def start(admin, b):
    r = admin.post(
        API + f"/widget/bots/{b['id']}/conversations",
        headers={"Origin": "https://shop.example"},
        json={},
    )
    assert r.status_code == 200, r.text
    s = r.json()
    s["headers"] = {
        "Origin": "https://shop.example",
        "Authorization": "Bearer " + s["token"],
    }
    return s


def message(admin, s, text="Hello", key="customer-1"):
    return admin.post(
        API + f"/widget/conversations/{s['conversation_id']}/messages",
        headers=s["headers"],
        json={"content": text, "client_id": key},
    )


def history(admin, s):
    r = admin.get(
        API + f"/widget/conversations/{s['conversation_id']}", headers=s["headers"]
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_setup_is_single_use_and_secrets_are_encrypted(admin, provider):
    assert (
        admin.post(
            API + "/auth/setup",
            json={
                "email": "bad@example.com",
                "password": "password-12345",
                "setup_token": "test-only-setup-token-32-characters",
            },
        ).status_code
        == 409
    )
    assert "never-expose-me" not in admin.get(API + "/credentials").text
    with Session() as db:
        cred = db.get(Credential, provider["credential"]["id"])
        assert cred.ciphertext != "never-expose-me"
        assert decrypt(cred.ciphertext) == "never-expose-me"
    assert (
        admin.post(
            API + "/auth/login",
            json={"email": "admin@example.com", "password": "wrong-password"},
        ).status_code
        == 401
    )


def test_complete_customer_to_agent_journey(admin, provider, drain):
    b = bot(admin)
    col = admin.post(
        API + "/collections",
        json={
            "name": "Returns",
            "bot_id": b["id"],
            "provider_id": provider["embedding"]["id"],
        },
    ).json()
    d = admin.post(
        API + f"/collections/{col['id']}/documents",
        files={
            "file": ("returns.md", b"Return orders within 30 days.", "text/markdown")
        },
    )
    assert d.status_code == 200, d.text
    drain()
    assert (
        admin.get(API + f"/collections/{col['id']}/documents").json()[0]["status"]
        == "ready"
    )
    definition = flow(
        [
            ("welcome", "message", {"text": "Welcome"}),
            ("ask", "input", {"variable": "question"}),
            ("route", "condition", {"variable": "question", "equals": "agent"}),
            (
                "answer",
                "ai",
                {
                    "provider_id": provider["generation"]["id"],
                    "collection_ids": [col["id"]],
                },
            ),
            ("handoff", "handoff", {}),
        ],
        [
            ("welcome", "next", "ask"),
            ("ask", "next", "route"),
            ("route", "true", "handoff"),
            ("route", "false", "answer"),
            ("answer", "next", "ask"),
            ("answer", "error", "handoff"),
        ],
    )
    publish(admin, b, definition)
    s = start(admin, b)
    drain()
    assert history(admin, s)["messages"][0]["content"] == "Welcome"
    assert message(admin, s, "How do I return an order?").status_code == 200
    drain()
    h = history(admin, s)
    answer = h["messages"][-1]
    assert "[1]" in answer["content"] and answer["sources"][0]["name"] == "returns.md"
    assert message(admin, s, "agent", "customer-2").status_code == 200
    drain()
    assert history(admin, s)["status"] == "queued"
    assert (
        admin.post(API + f"/conversations/{s['conversation_id']}/claim").status_code
        == 409
    )
    admin.post(API + "/users/availability", json={"available": True})
    assert (
        admin.post(API + f"/conversations/{s['conversation_id']}/claim").status_code
        == 200
    )
    assert (
        admin.post(API + f"/conversations/{s['conversation_id']}/claim").status_code
        == 409
    )
    assert (
        admin.post(
            API + f"/conversations/{s['conversation_id']}/messages",
            json={"content": "I can help", "client_id": "agent-1"},
        ).status_code
        == 200
    )
    assert (
        admin.post(
            API + f"/conversations/{s['conversation_id']}/notes",
            json={"content": "Internal only", "client_id": "note-1"},
        ).status_code
        == 200
    )
    assert "Internal only" not in json.dumps(history(admin, s))
    assert history(admin, s)["messages"][-1]["content"] == "I can help"
    admin.post(API + f"/conversations/{s['conversation_id']}/close")
    assert message(admin, s, "hello", "customer-3").status_code == 409
    m = admin.get(API + "/monitoring").json()
    assert (
        m["counts"]["closed"] == 1
        and m["handoffs"] == 1
        and m["closed_is_resolution"] is False
    )
    assert m["input_tokens"] == 12 and m["estimated_cost"] is None


def test_duplicate_messages_and_jobs_do_not_duplicate_replies(admin, drain):
    b = bot(admin)
    publish(admin, b)
    s = start(admin, b)
    drain()
    assert message(admin, s).status_code == 200
    assert message(admin, s).json()["duplicate"] is True
    drain()
    h = history(admin, s)
    assert len([m for m in h["messages"] if m["role"] == "customer"]) == 1
    assert len([m for m in h["messages"] if m["role"] == "bot"]) == 1
    with Session() as db:
        jobs = db.scalars(
            select(Job).where(Job.target_id == s["conversation_id"])
        ).all()
    for j in jobs:
        execute_step(j.id)
    assert history(admin, s) == h


def test_published_versions_are_pinned(admin, drain):
    b = bot(admin)
    v1 = publish(admin, b)
    s = start(admin, b)
    changed = b["draft"]
    changed["nodes"][0]["config"]["text"] = "New welcome"
    v2 = publish(admin, b, changed)
    drain()
    assert v1["id"] != v2["id"]
    assert history(admin, s)["version_id"] == v1["id"]
    assert history(admin, s)["messages"][0]["content"] != "New welcome"
    s2 = start(admin, b)
    drain()
    assert history(admin, s2)["messages"][0]["content"] == "New welcome"


@pytest.mark.parametrize(
    "code", ["authentication_failed", "rate_limited", "timeout", "iteration_limit"]
)
def test_provider_errors_follow_error_branch(admin, provider, drain, monkeypatch, code):
    def fail(*args, **kwargs):
        raise ProviderError(code)

    monkeypatch.setattr(providers.adapter, "generate", fail)
    b = bot(admin)
    definition = flow(
        [
            ("welcome", "ai", {"provider_id": provider["generation"]["id"]}),
            ("ok", "end", {}),
            ("bad", "handoff", {}),
        ],
        [("welcome", "next", "ok"), ("welcome", "error", "bad")],
    )
    publish(admin, b, definition)
    s = start(admin, b)
    drain()
    assert history(admin, s)["status"] == "queued"
    traces = admin.get(API + f"/conversations/{s['conversation_id']}/traces").json()
    assert traces[0]["detail"]["code"] == code


def test_handoff_discards_late_ai_output(admin, provider, drain, monkeypatch):
    b = bot(admin)
    definition = flow(
        [
            ("welcome", "ai", {"provider_id": provider["generation"]["id"]}),
            ("done", "end", {}),
            ("bad", "handoff", {}),
        ],
        [("welcome", "next", "done"), ("welcome", "error", "bad")],
    )
    publish(admin, b, definition)
    s = start(admin, b)

    def late(*args, **kwargs):
        r = admin.post(
            API + f"/widget/conversations/{s['conversation_id']}/handoff",
            headers=s["headers"],
        )
        assert r.status_code == 200
        return Reply(text="This must not be delivered")

    monkeypatch.setattr(providers.adapter, "generate", late)
    drain()
    h = history(admin, s)
    assert h["status"] == "queued"
    assert not h["messages"]


def test_expired_lease_reconciles_pending_step(admin, drain):
    b = bot(admin)
    publish(admin, b)
    s = start(admin, b)
    with Session() as db:
        jid = db.scalar(select(Job.id).where(Job.target_id == s["conversation_id"]))
    data = snapshot_step(jid)
    assert data
    with Session() as db:
        db.get(Job, jid).lease_until = time.time() - 1
        db.commit()
    execute_step(jid)
    drain()
    h = history(admin, s)
    assert len(h["messages"]) == 1 and h["messages"][0]["role"] == "bot"


def test_knowledge_scope_delete_and_reindex(admin, provider, drain):
    b = bot(admin)
    other = bot(admin)
    cid = admin.post(
        API + "/collections",
        json={
            "name": "FAQ",
            "bot_id": b["id"],
            "provider_id": provider["embedding"]["id"],
        },
    ).json()["id"]
    did = admin.post(
        API + f"/collections/{cid}/documents",
        files={"file": ("faq.txt", b"Return your order", "text/plain")},
    ).json()["id"]
    drain()
    with Session() as db:
        assert retrieve(db, b["id"], [cid], "returns")
        with pytest.raises(Exception, match="foreign_collection"):
            retrieve(db, other["id"], [cid], "returns")
    assert admin.post(API + f"/collections/{cid}/reindex", json={}).status_code == 200
    with Session() as db:
        assert not retrieve(db, b["id"], [cid], "returns")
    drain()
    assert admin.delete(API + f"/documents/{did}").status_code == 200
    with Session() as db:
        assert not retrieve(db, b["id"], [cid], "returns")


def test_invalid_upload_and_empty_text(admin, provider, drain):
    b = bot(admin)
    cid = admin.post(
        API + "/collections",
        json={
            "name": "FAQ",
            "bot_id": b["id"],
            "provider_id": provider["embedding"]["id"],
        },
    ).json()["id"]
    assert (
        admin.post(
            API + f"/collections/{cid}/documents", files={"file": ("bad.exe", b"bad")}
        ).status_code
        == 422
    )
    admin.post(
        API + f"/collections/{cid}/documents", files={"file": ("empty.txt", b"")}
    )
    drain()
    assert (
        admin.get(API + f"/collections/{cid}/documents").json()[0]["error"]
        == "no_extractable_text"
    )


def test_origin_and_conversation_capability_isolation(admin, drain):
    b = bot(admin)
    publish(admin, b)
    assert (
        admin.post(
            API + f"/widget/bots/{b['id']}/conversations",
            headers={"Origin": "https://evil.example"},
            json={},
        ).status_code
        == 403
    )
    assert (
        admin.post(
            API + "/queues",
            headers={"Origin": "https://evil.example"},
            json={"name": "bad"},
        ).status_code
        == 403
    )
    s = start(admin, b)
    s2 = start(admin, b)
    assert (
        admin.get(
            API + f"/widget/conversations/{s2['conversation_id']}", headers=s["headers"]
        ).status_code
        == 403
    )
    bad = {**s["headers"], "Origin": "https://evil.example"}
    assert (
        admin.get(
            API + f"/widget/conversations/{s['conversation_id']}", headers=bad
        ).status_code
        == 403
    )
    r = admin.options(
        API + "/widget/test",
        headers={
            "Origin": "https://shop.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert (
        r.status_code == 204
        and r.headers["access-control-allow-origin"] == "https://shop.example"
    )


def invite_user(admin, role, email):
    invited = admin.post(
        API + "/invitations", json={"email": email, "role": role}
    ).json()
    c = TestClient(app)
    r = c.post(
        API + "/auth/accept",
        json={
            "email": email,
            "password": "user-password-123",
            "invitation_token": invited["token"],
        },
    )
    assert r.status_code == 200, r.text
    return c


def test_role_permissions_and_single_use_invitation(admin):
    agent = invite_user(admin, "agent", "agent@example.com")
    assert agent.get(API + "/bots").status_code == 403
    assert agent.get(API + "/credentials").status_code == 403
    assert (
        agent.post(API + "/credentials", json={"name": "x", "secret": "x"}).status_code
        == 403
    )
    assert agent.get(API + "/conversations").status_code == 200
    builder = invite_user(admin, "builder", "builder@example.com")
    assert builder.get(API + "/bots").status_code == 200
    assert builder.get(API + "/users").status_code == 403
    assert builder.get(API + "/conversations").status_code == 403
    assert (
        builder.post(
            API + "/providers",
            json={"name": "x", "kind": "openai", "model": "x", "credential_id": "x"},
        ).status_code
        == 403
    )


def test_export_import_redacts_and_requires_bindings(admin, provider):
    b = bot(admin)
    f = flow(
        [
            ("welcome", "ai", {"provider_id": provider["generation"]["id"]}),
            ("end", "end", {}),
        ],
        [("welcome", "next", "end"), ("welcome", "error", "end")],
    )
    publish(admin, b, f)
    bundle = admin.get(API + f"/bots/{b['id']}/export").json()
    assert "never-expose-me" not in json.dumps(bundle)
    assert "credential_id" not in json.dumps(bundle)
    assert admin.post(API + "/bots/import", json={"bundle": bundle}).status_code == 422
    r = admin.post(
        API + "/bots/import",
        json={
            "bundle": bundle,
            "provider_bindings": {
                provider["generation"]["id"]: provider["generation"]["id"]
            },
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["bot"]["published_id"] is None and not r.json()["bot"]["origins"]


def test_flow_validation_rejects_bad_graphs_and_unsupported_capabilities(
    admin, provider
):
    assert validate_flow({"schema_version": 9})
    b = bot(admin)
    bad = flow([("welcome", "ai", {"provider_id": provider["embedding"]["id"]})], [])
    r = admin.put(API + f"/bots/{b['id']}/draft", json={"flow": bad})
    assert r.status_code == 200 and r.json()["errors"]
    assert admin.post(API + f"/bots/{b['id']}/publish").status_code == 422
    r = admin.put(
        API + f"/bots/{b['id']}/draft",
        json={
            "flow": {
                "schema_version": 1,
                "entry": "x",
                "nodes": [
                    {"id": "x", "type": "ai", "config": {"tool_ids": "not-a-list"}}
                ],
                "edges": [],
            }
        },
    )
    assert r.status_code == 200 and r.json()["errors"]


def test_websocket_snapshot_and_widget_note_isolation(admin, drain):
    b = bot(admin)
    publish(admin, b)
    s = start(admin, b)
    drain()
    with admin.websocket_connect(
        API + f"/events/{s['conversation_id']}",
        headers={"Origin": "https://shop.example"},
    ) as ws:
        ws.send_json({"token": s["token"]})
        first = ws.receive_json()
        assert first["kind"] == "snapshot" and first["payload"]["messages"]
        admin.post(
            API + f"/conversations/{s['conversation_id']}/notes",
            json={"content": "secret note", "client_id": "note"},
        )
        event = ws.receive_json()
        assert "secret note" not in json.dumps(event)


def test_unsafe_tool_is_not_repeated_after_uncertain_outcome(admin, drain, monkeypatch):
    b = bot(admin)
    publish(admin, b)
    s = start(admin, b)
    drain()
    with Session() as db:
        t = Tool(
            name="test",
            url="https://tools.example/action",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            safe_retry=False,
        )
        db.add(t)
        db.flush()
        db.add(
            Invocation(
                conversation_id=s["conversation_id"],
                tool_id=t.id,
                invocation_key="stable-action",
                status="started",
            )
        )
        db.commit()
    monkeypatch.setattr("app.tools.outbound_url", lambda *a: None)
    with pytest.raises(UncertainOutcome):
        call_tool(t, {}, s["conversation_id"], "stable-action")
    with Session() as db:
        assert (
            db.scalar(
                select(Invocation).where(Invocation.invocation_key == "stable-action")
            ).status
            == "uncertain"
        )


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="Requires TEST_DATABASE_URL pointing to PostgreSQL",
)
def test_concurrent_agent_claim_only_one_wins(admin, drain):
    from concurrent.futures import ThreadPoolExecutor

    b = bot(admin)
    publish(admin, b)
    s = start(admin, b)
    drain()
    message(admin, s)
    drain()
    a = invite_user(admin, "agent", "a@example.com")
    c = invite_user(admin, "agent", "c@example.com")
    for user in (a, c):
        assert (
            user.post(API + "/users/availability", json={"available": True}).status_code
            == 200
        )
    with ThreadPoolExecutor(2) as pool:
        codes = list(
            pool.map(
                lambda user: user.post(
                    API + f"/conversations/{s['conversation_id']}/claim"
                ).status_code,
                (a, c),
            )
        )
    assert sorted(codes) == [200, 409]


def test_customer_ids_cannot_reserve_bot_message_keys(admin, drain):
    b = bot(admin)
    publish(admin, b)
    s = start(admin, b)
    assert message(admin, s, "Hello", "step:0").status_code == 200
    drain()
    h = history(admin, s)
    assert any(m["role"] == "bot" for m in h["messages"])
    assert any(m["role"] == "customer" for m in h["messages"])


def test_post_history_supports_widget_resume(admin, drain):
    b = bot(admin)
    publish(admin, b)
    s = start(admin, b)
    drain()
    r = admin.post(
        API + f"/widget/conversations/{s['conversation_id']}/history",
        headers=s["headers"],
        json={},
    )
    assert r.status_code == 200 and r.json()["messages"]


def test_templates_preserve_typed_tool_arguments():
    from app.flows import render

    variables = {"count": 3, "order": {"id": "123"}}
    assert render({"count": "${count}", "order": "${order}"}, variables) == variables
    assert render("Count: ${count}", variables) == "Count: 3"


@pytest.mark.parametrize(
    "bad",
    [
        {
            "schema_version": 1,
            "entry": "x",
            "nodes": [{"id": "x", "type": {}, "config": {}}],
            "edges": [],
        },
        {
            "schema_version": 1,
            "entry": "x",
            "nodes": [{"id": "x", "type": "end", "config": {}}],
            "edges": [{"source": {}, "target": "x"}],
        },
    ],
)
def test_malformed_workflows_are_validation_errors(bad):
    assert validate_flow(bad)


def test_api_reference_is_local_and_schema_is_published(client):
    r = client.get(API + "/docs")
    assert r.status_code == 200 and "cdn.jsdelivr" not in r.text
    assert client.get(API + "/docs.js").status_code == 200
    schema = client.get(API + "/openapi.json").json()
    assert API + "/bots" in schema["paths"]


def test_invitation_reuse_is_rejected(admin):
    invited = admin.post(
        API + "/invitations", json={"email": "new@example.com", "role": "agent"}
    ).json()
    payload = {
        "email": "new@example.com",
        "password": "password-for-invite-123",
        "invitation_token": invited["token"],
    }
    with TestClient(app) as c:
        assert c.post(API + "/auth/accept", json=payload).status_code == 200
        assert c.post(API + "/auth/accept", json=payload).status_code == 400


def test_validation_errors_do_not_echo_credentials(admin):
    secret = "sensitive-marker-" * 1000
    r = admin.post(API + "/credentials", json={"name": "invalid", "secret": secret})
    assert r.status_code == 422
    assert "sensitive-marker" not in r.text


def test_new_bot_default_handoff_uses_general_queue(admin, drain):
    b = bot(admin)
    general = next(
        q["id"] for q in admin.get(API + "/queues").json() if q["name"] == "General"
    )
    assert b["draft"]["nodes"][-1]["config"]["queue_id"] == general
    publish(admin, b)
    s = start(admin, b)
    drain()
    message(admin, s)
    drain()
    assert history(admin, s)["queue_id"] == general


def test_explicit_unassigned_handoff_does_not_use_an_empty_foreign_key(admin, drain):
    b = bot(admin)
    publish(admin, b, flow([("welcome", "handoff", {"queue_id": ""})], []))
    s = start(admin, b)
    drain()
    h = history(admin, s)
    assert h["status"] == "queued" and h["queue_id"] is None
