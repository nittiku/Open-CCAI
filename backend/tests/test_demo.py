import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select, func
from app import providers, runtime
from app.db import Session, engine
from app.demo import (
    seed_demo,
    DemoAdapter,
    demo_tool_executor,
    DEMO_EMAIL,
    DEMO_PASSWORD,
)
from app.models import User, Project, Provider, Tool, Invocation
from app.security import passwords
from test_platform import API, message, history


def test_normal_startup_does_not_create_demo_login(client):
    assert client.get(API + "/auth/status").json()["initialized"] is False
    assert (
        client.post(
            API + "/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
        ).status_code
        == 401
    )


@pytest.mark.skipif(
    engine.dialect.name != "sqlite",
    reason="Demo playground intentionally uses SQLite only",
)
def test_demo_login_persistent_seed_and_mock_routing(client, drain, monkeypatch):
    monkeypatch.setattr(providers, "adapter", DemoAdapter(providers.adapter))
    monkeypatch.setattr(runtime, "call_tool", demo_tool_executor)
    with Session() as db:
        assert seed_demo(db) is True
        project = db.scalar(select(Project))
        original_name = project.name
        project.name = "My edited playground"
        db.commit()
        assert seed_demo(db) is False
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(Project)).name == "My edited playground"
        user = db.scalar(select(User))
        assert user.role == "administrator" and passwords.verify(
            DEMO_PASSWORD, user.password
        )
    r = client.post(
        API + "/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert r.status_code == 200, r.text
    p = client.get(API + "/projects").json()[0]
    drain()
    r = client.post(API + f"/projects/{p['id']}/test")
    assert r.status_code == 200, r.text
    s = r.json()
    s["headers"] = {"Authorization": "Bearer " + s["token"]}
    drain()
    assert "Welcome to the demo" in history(client, s)["messages"][0]["content"]
    message(client, s, "I want to return an order")
    drain()
    answer = history(client, s)["messages"][-1]
    assert (
        "30 days" in answer["content"]
        and answer["sources"][0]["name"] == "Demo store guide.md"
    )
    message(client, s, "track order DEMO-1001", "tracking")
    drain()
    assert "shipped" in history(client, s)["messages"][-1]["content"]
    with Session() as db:
        invocation = db.scalar(select(Invocation))
        assert invocation.status == "succeeded" and invocation.result["demo"] is True
        tool = db.get(Tool, invocation.tool_id)
        assert (
            demo_tool_executor(
                tool,
                {"order_id": "DEMO-1001"},
                s["conversation_id"],
                invocation.invocation_key,
            )
            == invocation.result
        )
    message(client, s, "talk to a person", "handoff")
    drain()
    assert history(client, s)["status"] == "queued"
    assert (
        client.post(API + f"/conversations/{s['conversation_id']}/claim").status_code
        == 200
    )


def test_demo_adapter_delegates_real_providers():
    delegate = MagicMock()
    adapter = DemoAdapter(delegate)
    db = MagicMock()
    p = Provider(
        name="Real connection",
        kind="openai",
        model="organization-model",
        purpose="generation",
        credential_id="key",
    )
    callback = lambda text: None
    adapter.generate(db, p, [], [], callback)
    delegate.generate.assert_called_once_with(
        db, p, [], [], callback, timeout=30, output_schema=None
    )
    adapter.embed(db, p, ["hello"])
    delegate.embed.assert_called_once_with(db, p, ["hello"])


def test_demo_environment_ignores_production_database_and_preserves_private_keys(
    tmp_path,
):
    root = Path(__file__).resolve().parents[2]
    marker = tmp_path / ".env"
    marker.write_text("PRIVATE_PRODUCTION_CONFIGURATION=unchanged\n")
    code = f"""
import importlib.util,os,json,hashlib
from pathlib import Path
spec=importlib.util.spec_from_file_location('demo_script',{str(root/'scripts/demo.py')!r})
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.root=Path({str(tmp_path)!r});module.configure_environment()
first=(module.root/'data/demo/secrets.json').read_bytes()
module.configure_environment()
assert first==(module.root/'data/demo/secrets.json').read_bytes()
print(json.dumps({{'database':os.environ['DATABASE_URL'],'storage':os.environ['STORAGE_PATH'],'secret_changed':os.environ['APP_SECRET']!='production-placeholder'}}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env={
            **os.environ,
            "DATABASE_URL": "postgresql://production.invalid/never-connect",
            "APP_SECRET": "production-placeholder",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout)
    assert values["database"] == "sqlite:///" + str(tmp_path / "data/demo/demo.db")
    assert values["secret_changed"] is True
    assert marker.read_text() == "PRIVATE_PRODUCTION_CONFIGURATION=unchanged\n"
    if os.name == "posix":
        assert (tmp_path / "data/demo/secrets.json").stat().st_mode & 0o777 == 0o600
