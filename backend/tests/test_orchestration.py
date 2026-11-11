import json
import pytest
from sqlalchemy import select
from app.db import Session
from app.models import (
    Project,
    ProjectVersion,
    Agent,
    AgentVersion,
    Tool,
    Trace,
    Collection,
    Bot,
    Conversation,
    Message,
    Version,
)
from app import providers
from app.providers import Reply, ProviderError
from test_platform import API, flow, publish, message, history, bot


def project(admin, provider):
    r = admin.post(
        API + "/projects",
        json={
            "name": "Customer service",
            "description": "Support for online orders",
            "purpose": "Resolve order and return questions",
            "origins": ["https://shop.example"],
            "orchestrator": {
                "provider_id": provider["generation"]["id"],
                "description": "Customer request router",
                "purpose": "Choose the order intent or specialist agent",
                "flow_ids": [],
                "agent_ids": [],
                "welcome": "What can we help you with?",
            },
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def intent(admin, p, name="Returns", definition=None):
    r = admin.post(
        API + "/bots",
        json={
            "project_id": p["id"],
            "name": name,
            "description": "A guided return request",
            "purpose": "Start when the customer wants to return an order",
        },
    )
    assert r.status_code == 200, r.text
    b = r.json()
    publish(
        admin,
        b,
        definition
        or flow(
            [
                ("welcome", "message", {"text": "Return your order within 30 days."}),
                ("end", "end", {}),
            ],
            [("welcome", "next", "end")],
        ),
    )
    return b


def full_agent(
    admin,
    p,
    provider,
    instructions="Answer customer questions",
    tools=None,
    collections=None,
):
    r = admin.post(
        API + "/agents",
        json={
            "project_id": p["id"],
            "name": "Order specialist",
            "description": "An independent order expert",
            "purpose": "Help with order status and shipping",
            "definition": {
                "provider_id": provider["generation"]["id"],
                "instructions": instructions,
                "tool_ids": tools or [],
                "collection_ids": collections or [],
                "max_iterations": 4,
            },
        },
    )
    assert r.status_code == 200, r.text
    a = r.json()
    r = admin.post(API + f"/agents/{a['id']}/publish")
    assert r.status_code == 200, r.text
    return a


def configure(admin, p, flows=None, agents=None):
    body = {
        k: p[k] for k in ("name", "description", "purpose", "origins", "orchestrator")
    }
    body["orchestrator"] = {
        **p["orchestrator"],
        "flow_ids": [b["id"] for b in flows or []],
        "agent_ids": [a["id"] for a in agents or []],
    }
    r = admin.put(API + f"/projects/{p['id']}", json=body)
    assert r.status_code == 200, r.text
    p.update(r.json())
    r = admin.post(API + f"/projects/{p['id']}/publish")
    assert r.status_code == 200, r.text
    return r.json()


def start_project(admin, p):
    r = admin.post(
        API + f"/widget/projects/{p['id']}/conversations",
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


def scripted(monkeypatch, decisions):
    original = providers.adapter.generate
    seen = []

    def generate(db, provider, messages, tools, on_chunk, **kwargs):
        if messages[0]["content"].startswith("You route contact-center requests"):
            seen.append(messages[0]["content"])
            decision = decisions.pop(0)
            if isinstance(decision, Exception):
                raise decision
            return Reply(text=json.dumps(decision), input_tokens=3, output_tokens=2)
        return original(db, provider, messages, tools, on_chunk, **kwargs)

    monkeypatch.setattr(providers.adapter, "generate", generate)
    return seen


def test_project_routes_to_flow_then_agent_and_returns_to_orchestrator(
    admin, provider, drain, monkeypatch
):
    p = project(admin, provider)
    b = intent(admin, p)
    a = full_agent(admin, p, provider)
    release = configure(admin, p, [b], [a])
    seen = scripted(
        monkeypatch,
        [
            {"target_type": "flow", "target_id": b["id"]},
            {"target_type": "agent", "target_id": a["id"]},
        ],
    )
    s = start_project(admin, p)
    drain()
    assert (
        len(seen) == 0
        and history(admin, s)["messages"][0]["content"] == "What can we help you with?"
    )
    message(admin, s, "I want to return an order")
    drain()
    h = history(admin, s)
    assert (
        h["status"] == "bot" and h["execution_mode"] == "orchestrator" and h["waiting"]
    )
    assert h["messages"][-1]["content"] == "Return your order within 30 days."
    message(admin, s, "Where is my shipment?", "second")
    drain()
    h = history(admin, s)
    assert (
        h["execution_mode"] == "orchestrator"
        and h["project_version_id"] == release["id"]
    )
    assert "answer from your knowledge" in h["messages"][-1]["content"]
    assert (
        len(seen) == 2
        and "Customer request router" in seen[0]
        and "Start when" in seen[0]
    )
    with Session() as db:
        assert all(
            m.consumed
            for m in db.scalars(
                select(Message).where(
                    Message.conversation_id == s["conversation_id"],
                    Message.role == "customer",
                )
            )
        )
    with admin.websocket_connect(
        API + f"/events/{s['conversation_id']}",
        headers={"Origin": "https://shop.example"},
    ) as ws:
        ws.send_json({"token": s["token"]})
        assert ws.receive_json()["kind"] == "snapshot"


def test_active_intent_collects_input_before_returning_to_router(
    admin, provider, drain, monkeypatch
):
    p = project(admin, provider)
    b = intent(
        admin,
        p,
        definition=flow(
            [
                ("welcome", "message", {"text": "What is your order number?"}),
                ("input", "input", {"variable": "order"}),
                ("reply", "message", {"text": "Looking up ${order}"}),
                ("end", "end", {}),
            ],
            [
                ("welcome", "next", "input"),
                ("input", "next", "reply"),
                ("reply", "next", "end"),
            ],
        ),
    )
    configure(admin, p, [b])
    seen = scripted(monkeypatch, [{"target_type": "flow", "target_id": b["id"]}])
    s = start_project(admin, p)
    drain()
    message(admin, s, "Return an order")
    drain()
    assert history(admin, s)["execution_mode"] == "flow"
    message(admin, s, "ORDER-42", "order-number")
    drain()
    h = history(admin, s)
    assert h["messages"][-1]["content"] == "Looking up ORDER-42"
    assert h["execution_mode"] == "orchestrator" and len(seen) == 1


@pytest.mark.parametrize(
    "decision",
    [
        {"target_type": "agent", "target_id": "not-enabled"},
        {"target_type": "unknown"},
        ProviderError("rate_limited"),
    ],
)
def test_invalid_or_failed_routing_hands_off_instead_of_inventing_targets(
    admin, provider, drain, monkeypatch, decision
):
    p = project(admin, provider)
    b = intent(admin, p)
    configure(admin, p, [b])
    scripted(monkeypatch, [decision])
    s = start_project(admin, p)
    drain()
    message(admin, s)
    drain()
    assert history(admin, s)["status"] == "queued"
    rows = admin.get(API + f"/conversations/{s['conversation_id']}/traces").json()
    assert any(t["node_id"] == "orchestrator" and t["status"] == "error" for t in rows)


def test_ambiguity_asks_clarification_then_routes(admin, provider, drain, monkeypatch):
    p = project(admin, provider)
    b = intent(admin, p)
    configure(admin, p, [b])
    scripted(
        monkeypatch,
        [
            {"target_type": "clarify", "message": "Do you want to return an order?"},
            {"target_type": "flow", "target_id": b["id"]},
        ],
    )
    s = start_project(admin, p)
    drain()
    message(admin, s, "An order")
    drain()
    assert (
        history(admin, s)["messages"][-1]["content"]
        == "Do you want to return an order?"
    )
    message(admin, s, "Yes, a return", "clarification")
    drain()
    assert history(admin, s)["messages"][-1]["content"].startswith("Return your order")


def test_project_catalog_cannot_reference_other_projects_or_unpublished_targets(
    admin, provider
):
    p = project(admin, provider)
    other = project(admin, provider)
    b = intent(admin, other)
    body = {
        k: p[k] for k in ("name", "description", "purpose", "origins", "orchestrator")
    }
    body["orchestrator"] = {**p["orchestrator"], "flow_ids": [b["id"]]}
    admin.put(API + f"/projects/{p['id']}", json=body)
    assert admin.post(API + f"/projects/{p['id']}/publish").status_code == 422
    unpublished = admin.post(
        API + "/bots", json={"name": "Unpublished", "project_id": p["id"]}
    ).json()
    body["orchestrator"]["flow_ids"] = [unpublished["id"]]
    admin.put(API + f"/projects/{p['id']}", json=body)
    assert admin.post(API + f"/projects/{p['id']}/publish").status_code == 422


def test_agent_versions_are_pinned_by_project_and_flow_publication(
    admin, provider, drain, monkeypatch
):
    p = project(admin, provider)
    a = full_agent(admin, p, provider, instructions="OLD AGENT")
    b = intent(
        admin,
        p,
        definition=flow(
            [("welcome", "agent", {"agent_id": a["id"]}), ("end", "end", {})],
            [("welcome", "next", "end"), ("welcome", "error", "end")],
        ),
    )
    configure(admin, p, [b], [a])
    s = start_project(admin, p)
    drain()
    old_id = admin.get(API + "/agents").json()[0]["published_id"]
    changed = {k: a[k] for k in ("name", "description", "purpose", "project_id")}
    changed["definition"] = {**a["draft"], "instructions": "NEW AGENT"}
    admin.put(API + f"/agents/{a['id']}", json=changed)
    admin.post(API + f"/agents/{a['id']}/publish")
    seen = []
    base = providers.adapter.generate

    def generate(db, p, messages, tools, on_chunk, **kwargs):
        if not messages[0]["content"].startswith("You route"):
            seen.append(messages[0]["content"])
        return base(db, p, messages, tools, on_chunk, **kwargs)

    monkeypatch.setattr(providers.adapter, "generate", generate)
    scripted(
        monkeypatch,
        [
            {"target_type": "agent", "target_id": a["id"]},
            {"target_type": "flow", "target_id": b["id"]},
        ],
    )
    message(admin, s, "Specialist please")
    drain()
    message(admin, s, "Use the flow", "second")
    drain()
    assert len(seen) == 2 and all(
        "OLD AGENT" in text and "NEW AGENT" not in text for text in seen
    )
    with Session() as db:
        v = db.get(Version, db.get(Bot, b["id"]).published_id)
        assert v.flow["nodes"][0]["config"]["agent_version_id"] == old_id


def test_full_and_mini_agents_use_same_shared_tool_executor(
    admin, provider, drain, monkeypatch
):
    p = project(admin, provider)
    with Session() as db:
        t = Tool(
            name="lookup_order",
            url="https://tools.example/order",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            safe_retry=True,
        )
        db.add(t)
        db.commit()
    a = full_agent(admin, p, provider, instructions="FULL", tools=[t.id])
    b = intent(
        admin,
        p,
        definition=flow(
            [
                (
                    "welcome",
                    "ai",
                    {
                        "provider_id": provider["generation"]["id"],
                        "instructions": "MINI",
                        "tool_ids": [t.id],
                    },
                ),
                ("end", "end", {}),
            ],
            [("welcome", "next", "end"), ("welcome", "error", "end")],
        ),
    )
    configure(admin, p, [b], [a])
    original = providers.adapter.generate
    seen = []

    def generate(db, p, messages, tools, on_chunk, **kwargs):
        if messages[0]["content"].startswith("You route"):
            return original(db, p, messages, tools, on_chunk, **kwargs)
        assert tools[0]["function"]["name"] == "lookup_order"
        if messages[-1]["role"] != "tool":
            return Reply(
                calls=[
                    {
                        "id": "call1",
                        "type": "function",
                        "function": {"name": "lookup_order", "arguments": "{}"},
                    }
                ]
            )
        return Reply(text="Order found")

    monkeypatch.setattr(providers.adapter, "generate", generate)
    monkeypatch.setattr(
        "app.runtime.call_tool",
        lambda tool, args, cid, key: seen.append((tool.id, key)) or {"found": True},
    )
    scripted(
        monkeypatch,
        [
            {"target_type": "agent", "target_id": a["id"]},
            {"target_type": "flow", "target_id": b["id"]},
        ],
    )
    s = start_project(admin, p)
    drain()
    message(admin, s, "Agent")
    drain()
    message(admin, s, "Intent", "second")
    drain()
    assert len(seen) == 2 and all(tid == t.id for tid, _ in seen)
    assert seen[0][1] != seen[1][1]


def test_full_agent_cannot_use_foreign_knowledge_or_flow_agent(admin, provider):
    p = project(admin, provider)
    other = project(admin, provider)
    b = intent(admin, other)
    c = admin.post(
        API + "/collections",
        json={
            "name": "Private",
            "bot_id": b["id"],
            "provider_id": provider["embedding"]["id"],
        },
    ).json()
    a = admin.post(
        API + "/agents",
        json={
            "project_id": p["id"],
            "name": "Bad",
            "description": "Bad",
            "purpose": "Bad",
            "definition": {
                "provider_id": provider["generation"]["id"],
                "instructions": "Help",
                "collection_ids": [c["id"]],
            },
        },
    ).json()
    assert admin.post(API + f"/agents/{a['id']}/publish").status_code == 422
    foreign = full_agent(admin, other, provider)
    own = admin.post(API + "/bots", json={"project_id": p["id"], "name": "Own"}).json()
    f = flow(
        [("welcome", "agent", {"agent_id": foreign["id"]}), ("end", "end", {})],
        [("welcome", "next", "end"), ("welcome", "error", "end")],
    )
    admin.put(API + f"/bots/{own['id']}/draft", json={"flow": f})
    assert admin.post(API + f"/bots/{own['id']}/publish").status_code == 422


def test_agent_draft_test_does_not_publish_or_require_orchestrator_configuration(
    admin, provider, drain
):
    p = admin.post(API + "/projects", json={"name": "Draft project"}).json()
    a = admin.post(
        API + "/agents",
        json={
            "project_id": p["id"],
            "name": "Draft agent",
            "definition": {
                "provider_id": provider["generation"]["id"],
                "instructions": "Help customers",
            },
        },
    ).json()
    r = admin.post(API + f"/agents/{a['id']}/test")
    assert r.status_code == 200, r.text
    s = r.json()
    s["headers"] = {"Authorization": "Bearer " + s["token"]}
    drain()
    message(admin, s, "Help me")
    drain()
    assert history(admin, s)["messages"][-1]["content"].startswith("Here is the answer")
    assert admin.get(API + "/agents").json()[0]["published_id"] is None
    assert admin.get(API + "/projects").json()[0]["published_id"] is None


def test_project_widget_origin_and_capability_scope(admin, provider, drain):
    p = project(admin, provider)
    b = intent(admin, p)
    configure(admin, p, [b])
    assert (
        admin.post(
            API + f"/widget/projects/{p['id']}/conversations",
            headers={"Origin": "https://untrusted.example"},
            json={},
        ).status_code
        == 403
    )
    s = start_project(admin, p)
    other = start_project(admin, p)
    assert (
        admin.get(
            API + f"/widget/conversations/{other['conversation_id']}",
            headers=s["headers"],
        ).status_code
        == 403
    )


def test_flow_export_rebinds_full_agents_in_destination_project(admin, provider):
    p = project(admin, provider)
    a = full_agent(admin, p, provider)
    b = intent(
        admin,
        p,
        definition=flow(
            [("welcome", "agent", {"agent_id": a["id"]}), ("end", "end", {})],
            [("welcome", "next", "end"), ("welcome", "error", "end")],
        ),
    )
    bundle = admin.get(API + f"/bots/{b['id']}/export").json()
    assert bundle["agents"] == [{"ref": a["id"], "name": a["name"]}]
    assert (
        admin.post(
            API + "/bots/import", json={"project_id": p["id"], "bundle": bundle}
        ).status_code
        == 422
    )
    r = admin.post(
        API + "/bots/import",
        json={
            "project_id": p["id"],
            "bundle": bundle,
            "agent_bindings": {a["id"]: a["id"]},
        },
    )
    assert r.status_code == 200, r.text
    imported = r.json()["bot"]
    assert imported["project_id"] == p["id"] and imported["purpose"] == b["purpose"]
    assert admin.post(API + f"/bots/{imported['id']}/publish").status_code == 200


def test_buffered_requests_are_routed_and_answered_in_order(
    admin, provider, drain, monkeypatch
):
    p = project(admin, provider)
    a = full_agent(admin, p, provider)
    configure(admin, p, agents=[a])
    routed = []
    answered = []

    def generate(db, p, messages, tools, on_chunk, **kwargs):
        latest = messages[-1]["content"]
        if messages[0]["content"].startswith("You route"):
            routed.append(latest)
            return Reply(
                text=json.dumps({"target_type": "agent", "target_id": a["id"]})
            )
        answered.append(latest)
        return Reply(text="Answer to " + latest)

    monkeypatch.setattr(providers.adapter, "generate", generate)
    s = start_project(admin, p)
    drain()
    message(admin, s, "First request", "first")
    message(admin, s, "Second request", "second")
    drain()
    assert routed == ["First request", "Second request"]
    assert answered == routed


def test_handoff_during_full_agent_execution_uses_project_queue_and_discards_late_output(
    admin, provider, drain, monkeypatch
):
    p = project(admin, provider)
    queue = admin.post(API + "/queues", json={"name": "Specialists"}).json()
    p["orchestrator"]["fallback_queue_id"] = queue["id"]
    a = full_agent(admin, p, provider)
    configure(admin, p, agents=[a])
    s = start_project(admin, p)
    drain()

    def generate(db, p, messages, tools, on_chunk, **kwargs):
        if messages[0]["content"].startswith("You route"):
            return Reply(
                text=json.dumps({"target_type": "agent", "target_id": a["id"]})
            )
        r = admin.post(
            API + f"/widget/conversations/{s['conversation_id']}/handoff",
            headers=s["headers"],
        )
        assert r.status_code == 200, r.text
        return Reply(text="Discard this late automated answer")

    monkeypatch.setattr(providers.adapter, "generate", generate)
    message(admin, s, "Help with delivery")
    drain()
    h = history(admin, s)
    assert h["status"] == "queued" and h["queue_id"] == queue["id"]
    assert all(
        m["content"] != "Discard this late automated answer" for m in h["messages"]
    )
