"""Actual PostgreSQL dump/restore round-trip, opt-in to local PostgreSQL tools."""

import os
from pathlib import Path
import subprocess
import tarfile
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as RestoreSession
from app.db import engine
from app.models import Credential, Document, Message, Conversation
from app.knowledge import retrieve
from app.security import decrypt
from app.storage import storage
from test_platform import bot, publish, start, message, API


@pytest.mark.skipif(
    engine.dialect.name != "postgresql" or not os.getenv("TEST_PG_BIN"),
    reason="Requires PostgreSQL and TEST_PG_BIN client tools",
)
def test_database_files_and_encryption_survive_restore(
    admin, provider, drain, tmp_path
):
    b = bot(admin)
    cid = admin.post(
        API + "/collections",
        json={
            "name": "Backup knowledge",
            "bot_id": b["id"],
            "provider_id": provider["embedding"]["id"],
        },
    ).json()["id"]
    did = admin.post(
        API + f"/collections/{cid}/documents",
        files={
            "file": ("policy.md", b"Return your order within 30 days.", "text/markdown")
        },
    ).json()["id"]
    publish(admin, b)
    s = start(admin, b)
    drain()
    message(admin, s)
    drain()
    from app.db import Session

    with Session() as db:
        key = db.get(Document, did).storage_key
        original = storage.read(key)
    archive = tmp_path / "uploads.tar"
    with tarfile.open(archive, "w") as tar:
        tar.add(storage.path(key), arcname=key)
    url = engine.url
    env = {
        **os.environ,
        "PGHOST": url.host or "localhost",
        "PGPORT": str(url.port or 5432),
        "PGUSER": url.username or "postgres",
        "PGPASSWORD": url.password or "",
        "PGDATABASE": url.database,
    }
    binaries = Path(os.environ["TEST_PG_BIN"])
    dump = tmp_path / "database.dump"
    subprocess.run(
        [str(binaries / "pg_dump"), "-Fc", "-f", str(dump)],
        env=env,
        check=True,
        capture_output=True,
    )
    restored_name = "ccai_restore_" + uuid.uuid4().hex[:10]
    subprocess.run(
        [str(binaries / "createdb"), restored_name],
        env=env,
        check=True,
        capture_output=True,
    )
    restored_engine = None
    try:
        subprocess.run(
            [
                str(binaries / "pg_restore"),
                "--exit-on-error",
                "-d",
                restored_name,
                str(dump),
            ],
            env=env,
            check=True,
            capture_output=True,
        )
        restored_engine = create_engine(url.set(database=restored_name))
        with RestoreSession(restored_engine) as db:
            assert db.get(Conversation, s["conversation_id"]).status == "queued"
            assert db.scalars(
                select(Message).where(Message.conversation_id == s["conversation_id"])
            ).all()
            credential = db.get(Credential, provider["credential"]["id"])
            assert decrypt(credential.ciphertext) == "never-expose-me"
            assert retrieve(db, b["id"], [cid], "return")[0]["name"] == "policy.md"
        restored_files = tmp_path / "restored-uploads"
        with tarfile.open(archive) as tar:
            tar.extractall(restored_files, filter="data")
        assert (restored_files / key).read_bytes() == original
    finally:
        if restored_engine:
            restored_engine.dispose()
        subprocess.run(
            [str(binaries / "dropdb"), restored_name],
            env=env,
            check=True,
            capture_output=True,
        )
