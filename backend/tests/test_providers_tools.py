import json
import os
import sys
import time
from types import SimpleNamespace as Obj
from unittest.mock import MagicMock
import pytest
import httpx
from sqlalchemy import select
from app.providers import LiteLLMAdapter, ProviderError, Reply
from app.models import Provider, Credential, Invocation, Tool, Job
from app.db import Session
from app.security import encrypt, outbound_url
from app.tools import call_tool, ToolError
from app import providers
from test_platform import bot, flow, publish, start, history, API


@pytest.mark.parametrize(
    "kind,prefix",
    [
        ("openai", "openai"),
        ("anthropic", "anthropic"),
        ("gemini", "gemini"),
        ("compatible", "openai"),
    ],
)
def test_native_adapter_routing_and_streaming(monkeypatch, kind, prefix):
    kwargs = {}
    chunks = [
        Obj(usage=None, choices=[Obj(delta=Obj(content="hello", tool_calls=[]))]),
        Obj(usage=Obj(prompt_tokens=3, completion_tokens=2), choices=[]),
    ]

    def completion(**kw):
        kwargs.update(kw)
        return iter(chunks)

    monkeypatch.setitem(sys.modules, "litellm", Obj(completion=completion))
    p = Provider(
        name=kind,
        kind=kind,
        model="test-model",
        purpose="generation",
        capabilities={"streaming": True},
        credential_id="key",
    )
    db = MagicMock()
    db.get.return_value = Obj(ciphertext=encrypt("provider-secret"))
    seen = []
    r = LiteLLMAdapter().generate(
        db, p, [{"role": "user", "content": "hello"}], [], seen.append
    )
    assert kwargs["model"] == prefix + "/test-model"
    assert kwargs["api_key"] == "provider-secret" and kwargs["num_retries"] == 0
    assert r.text == "hello" and r.input_tokens == 3 and seen == ["hello"]


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "authentication_failed"),
        (403, "authentication_failed"),
        (429, "rate_limited"),
        (500, "provider_error"),
    ],
)
def test_adapter_errors_never_expose_provider_payload(monkeypatch, status, code):
    class Failure(Exception):
        status_code = status

    def completion(**kwargs):
        raise Failure("secret-key-in-provider-error")

    monkeypatch.setitem(sys.modules, "litellm", Obj(completion=completion))
    p = Provider(
        name="p",
        kind="openai",
        model="test",
        purpose="generation",
        capabilities={},
        credential_id="key",
    )
    db = MagicMock()
    db.get.return_value = Obj(ciphertext=encrypt("secret-key-in-provider-error"))
    with pytest.raises(ProviderError) as exc:
        LiteLLMAdapter().generate(db, p, [], [], lambda _: None)
    assert str(exc.value) == code and "secret" not in str(exc.value)


def test_structured_output_capability_rejected_without_request(monkeypatch):
    request = MagicMock()
    monkeypatch.setitem(sys.modules, "litellm", Obj(completion=request))
    p = Provider(
        name="p", kind="openai", model="test", capabilities={}, credential_id="key"
    )
    db = MagicMock()
    db.get.return_value = Obj(ciphertext=encrypt("secret"))
    with pytest.raises(ProviderError, match="structured_unsupported"):
        LiteLLMAdapter().generate(
            db, p, [], [], lambda _: None, output_schema={"type": "object"}
        )
    request.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "http://tools.example/action",
        "https://user:pass@tools.example/action",
        "https://tools.example:444/action",
        "https://unlisted.example/action",
    ],
)
def test_outbound_destination_policy(url):
    with pytest.raises(ValueError):
        outbound_url(url, ("tools.example",))


def test_private_dns_and_redirects_are_blocked(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))]
    )
    with pytest.raises(ValueError, match="non-public"):
        outbound_url("https://tools.example/action", ("tools.example",))


def test_http_tool_output_validation_uncertainty_and_success_reuse(
    admin, drain, monkeypatch
):
    b = bot(admin)
    publish(admin, b)
    s = start(admin, b)
    drain()
    with Session() as db:
        t = Tool(
            name="lookup",
            url="https://tools.example/action",
            input_schema={
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "string"}},
            },
            output_schema={
                "type": "object",
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            },
            safe_retry=False,
            timeout=3,
        )
        db.add(t)
        db.commit()
    monkeypatch.setattr("app.tools.outbound_url", lambda *a: None)
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={"ok": True})

    real = httpx.Client
    monkeypatch.setattr(
        "app.tools.httpx.Client",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    assert call_tool(t, {"id": "1"}, s["conversation_id"], "one") == {"ok": True}
    assert call_tool(t, {"id": "1"}, s["conversation_id"], "one") == {"ok": True}
    assert len(sent) == 1 and sent[0].headers["Idempotency-Key"] == "one"

    def invalid(request):
        return httpx.Response(200, json={"wrong": True})

    monkeypatch.setattr(
        "app.tools.httpx.Client",
        lambda **kw: real(transport=httpx.MockTransport(invalid), **kw),
    )
    with pytest.raises(ToolError, match="uncertain"):
        call_tool(t, {"id": "1"}, s["conversation_id"], "two")
    with Session() as db:
        assert (
            db.scalar(
                select(Invocation).where(Invocation.invocation_key == "two")
            ).status
            == "uncertain"
        )


def test_ai_iteration_limit_preserves_usage_and_routes_to_human(
    admin, provider, drain, monkeypatch
):
    with Session() as db:
        t = Tool(
            name="noop",
            url="https://tools.example/action",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            safe_retry=True,
        )
        db.add(t)
        db.commit()

    def generate(*a, **kw):
        return Reply(
            calls=[
                {
                    "id": "call1",
                    "type": "function",
                    "function": {"name": "noop", "arguments": "{}"},
                }
            ],
            input_tokens=5,
            output_tokens=3,
        )

    monkeypatch.setattr(providers.adapter, "generate", generate)
    monkeypatch.setattr("app.runtime.call_tool", lambda *a, **kw: {"ok": True})
    b = bot(admin)
    f = flow(
        [
            (
                "welcome",
                "ai",
                {
                    "provider_id": provider["generation"]["id"],
                    "tool_ids": [t.id],
                    "max_iterations": 2,
                },
            ),
            ("ok", "end", {}),
            ("bad", "handoff", {}),
        ],
        [("welcome", "next", "ok"), ("welcome", "error", "bad")],
    )
    publish(admin, b, f)
    s = start(admin, b)
    drain()
    assert history(admin, s)["status"] == "queued"
    traces = admin.get(API + f"/conversations/{s['conversation_id']}/traces").json()
    assert any(t["detail"].get("code") == "iteration_limit" for t in traces)
    assert admin.get(API + "/monitoring").json()["input_tokens"] == 10


@pytest.mark.skipif(
    not os.getenv("TEST_BROKER_URL"), reason="Requires RabbitMQ TEST_BROKER_URL"
)
def test_real_broker_outbox_delivery(admin):
    from celery.contrib.testing.worker import start_worker
    from app.worker import celery, dispatch

    celery.conf.broker_url = os.environ["TEST_BROKER_URL"]
    b = bot(admin)
    publish(admin, b)
    s = start(admin, b)
    with start_worker(celery, perform_ping_check=False, pool="solo"):
        for _ in range(20):
            dispatch()
            if history(admin, s)["messages"]:
                break
            time.sleep(0.25)
    assert history(admin, s)["messages"][0]["role"] == "bot"


@pytest.mark.parametrize(
    "kind,env,model_env",
    [
        ("openai", "OPENAI_API_KEY", "OPENAI_TEST_MODEL"),
        ("anthropic", "ANTHROPIC_API_KEY", "ANTHROPIC_TEST_MODEL"),
        ("gemini", "GEMINI_API_KEY", "GEMINI_TEST_MODEL"),
    ],
)
def test_opt_in_live_provider(kind, env, model_env):
    if (
        os.getenv("RUN_LIVE_PROVIDER_TESTS") != "1"
        or not os.getenv(env)
        or not os.getenv(model_env)
    ):
        pytest.skip("Explicit opt-in, provider key, and model required")
    p = Provider(
        name="live-test",
        kind=kind,
        model=os.environ[model_env],
        purpose="generation",
        credential_id="key",
        capabilities={"streaming": True, "tools": True},
    )
    db = MagicMock()
    db.get.return_value = Obj(ciphertext=encrypt(os.environ[env]))
    reply = LiteLLMAdapter().generate(
        db,
        p,
        [{"role": "user", "content": "Reply with the word hello."}],
        [],
        lambda _: None,
    )
    assert reply.text.strip()
