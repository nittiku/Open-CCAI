"""Exercise an upgrade containing real legacy conversations, not only empty schemas."""

import os
import json
from pathlib import Path
import subprocess
import sys
import time
from sqlalchemy import create_engine, MetaData, Table, select, text
from app.flows import default_flow


def test_legacy_flows_and_history_survive_project_upgrade(tmp_path):
    path = tmp_path / "legacy.db"
    url = "sqlite:///" + str(path)
    cwd = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": url}

    def migrate(target):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", target],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    migrate("e71a057c841c")
    engine = create_engine(url)
    meta = MetaData()
    bots = Table("bots", meta, autoload_with=engine)
    versions = Table("versions", meta, autoload_with=engine)
    conversations = Table("conversations", meta, autoload_with=engine)
    messages = Table("messages", meta, autoload_with=engine)
    now = time.time()
    with engine.begin() as db:
        db.execute(
            bots.insert().values(
                id="legacy-flow",
                created=now,
                name="Existing support",
                origins=["https://legacy.example"],
                draft=default_flow(),
                published_id=None,
            )
        )
        db.execute(
            versions.insert().values(
                id="legacy-version",
                created=now,
                bot_id="legacy-flow",
                number=1,
                flow=default_flow(),
            )
        )
        db.execute(bots.update().values(published_id="legacy-version"))
        db.execute(
            conversations.insert().values(
                id="legacy-conversation",
                created=now,
                bot_id="legacy-flow",
                version_id="legacy-version",
                status="bot",
                node_id="question",
                variables={"question": "Existing question"},
                waiting=True,
                queue_id=None,
                agent_id=None,
                revision=0,
                steps=1,
                queued_at=None,
                closed_at=None,
            )
        )
        db.execute(
            messages.insert().values(
                id="legacy-message",
                created=now,
                conversation_id="legacy-conversation",
                role="bot",
                content="Preserve this transcript",
                client_id="legacy-client",
                sources=[],
                consumed=False,
            )
        )
    migrate("head")
    fresh = MetaData()
    projects = Table("projects", fresh, autoload_with=engine)
    bots = Table("bots", fresh, autoload_with=engine)
    conversations = Table("conversations", fresh, autoload_with=engine)
    with engine.connect() as db:
        p = db.execute(select(projects)).mappings().one()
        b = db.execute(select(bots)).mappings().one()
        c = db.execute(select(conversations)).mappings().one()
        assert b["project_id"] == p["id"] == c["project_id"]
        assert (
            b["published_id"] == "legacy-version"
            and c["version_id"] == "legacy-version"
        )
        assert (
            c["execution_mode"] == "flow"
            and c["project_version_id"] is None
            and c["variables"]["question"] == "Existing question"
        )
        assert p["published_id"] is None and p["origins"] == ["https://legacy.example"]
        assert (
            db.execute(select(messages.c.content)).scalar()
            == "Preserve this transcript"
        )
        assert not db.execute(text("PRAGMA foreign_key_check")).all()
    engine.dispose()
