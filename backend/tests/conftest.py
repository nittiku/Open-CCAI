import os
import tempfile
from pathlib import Path
import pytest
from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL",
    "sqlite:///" + str(Path(tempfile.gettempdir()) / f"ccai-tests-{os.getpid()}.db"),
)
os.environ["APP_SECRET"] = "test-only-secret-with-at-least-32-characters"
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["SETUP_TOKEN"] = "test-only-setup-token-32-characters"
os.environ["SECURE_COOKIE"] = "false"
os.environ["APP_ORIGINS"] = "http://testserver,http://localhost:5173"
os.environ["STORAGE_PATH"] = tempfile.mkdtemp(prefix="ccai-uploads-")
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

from fastapi.testclient import TestClient
from app.db import Base, engine, Session
from app.models import Installation, Job
from app.main import app
from app import providers
from app.providers import Reply
from app.runtime import execute_step
from app.knowledge import ingest


class MockAdapter:
    def generate(
        self, db, provider, messages, tools, on_chunk, timeout=30, output_schema=None
    ):
        text = "Here is the answer from your knowledge [1]."
        on_chunk("Here is ")
        on_chunk("the answer from your knowledge [1].")
        return Reply(text=text, input_tokens=12, output_tokens=9, latency_ms=15)

    def embed(self, db, provider, texts):
        return [
            [
                float(t.lower().count("return") + 1),
                float(t.lower().count("order") + 1),
                1.0,
            ]
            for t in texts
        ]


@pytest.fixture(autouse=True)
def database(monkeypatch):
    if engine.dialect.name == "postgresql":
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session() as db:
        db.add(Installation(id=1, initialized=False))
        db.commit()
    monkeypatch.setattr(providers, "adapter", MockAdapter())
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin(client):
    r = client.post(
        "/api/v1/auth/setup",
        json={
            "email": "admin@example.com",
            "password": "admin-password-123",
            "setup_token": os.environ["SETUP_TOKEN"],
        },
    )
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def provider(admin):
    c = admin.post(
        "/api/v1/credentials", json={"name": "test-key", "secret": "never-expose-me"}
    ).json()

    def create(purpose):
        return admin.post(
            "/api/v1/providers",
            json={
                "name": purpose,
                "kind": "openai",
                "model": "mock-" + purpose,
                "purpose": purpose,
                "credential_id": c["id"],
            },
        ).json()

    return {
        "generation": create("generation"),
        "embedding": create("embedding"),
        "credential": c,
    }


@pytest.fixture
def drain():
    from sqlalchemy import select

    def run():
        for _ in range(300):
            with Session() as db:
                pending = db.scalars(
                    select(Job).where(Job.status == "pending").order_by(Job.created)
                ).all()
            if not pending:
                return
            for job in pending:
                if job.kind == "conversation":
                    execute_step(job.id)
                else:
                    ingest(job.target_id)
                    with Session() as db:
                        db.get(Job, job.id).status = "done"
                        db.commit()
        raise AssertionError("Work did not settle")

    return run
