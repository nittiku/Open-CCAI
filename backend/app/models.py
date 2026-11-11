import time
import uuid
from sqlalchemy import (
    String,
    Text,
    Float,
    Integer,
    Boolean,
    JSON,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from .db import Base


def uid():
    return str(uuid.uuid4())


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Installation(Base):
    __tablename__ = "installation"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    initialized: Mapped[bool] = mapped_column(Boolean, default=False)


class User(Record, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20))
    available: Mapped[bool] = mapped_column(Boolean, default=False)


class Invitation(Record, Base):
    __tablename__ = "invitations"
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires: Mapped[float] = mapped_column(Float)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Credential(Record, Base):
    __tablename__ = "credentials"
    name: Mapped[str] = mapped_column(String(120))
    ciphertext: Mapped[str] = mapped_column(Text)


class Provider(Record, Base):
    __tablename__ = "providers"
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(160))
    purpose: Mapped[str] = mapped_column(String(20), default="generation")
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.id"))
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    pricing: Mapped[dict] = mapped_column(JSON, default=dict)


class Queue(Record, Base):
    __tablename__ = "queues"
    name: Mapped[str] = mapped_column(String(120), unique=True)


class Project(Record, Base):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    origins: Mapped[list] = mapped_column(JSON, default=list)
    orchestrator: Mapped[dict] = mapped_column(JSON, default=dict)
    published_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class ProjectVersion(Record, Base):
    __tablename__ = "project_versions"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    number: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("project_id", "number"),)


class Agent(Record, Base):
    __tablename__ = "agents"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    draft: Mapped[dict] = mapped_column(JSON, default=dict)
    published_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class AgentVersion(Record, Base):
    __tablename__ = "agent_versions"
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    number: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("agent_id", "number"),)


class Bot(Record, Base):
    __tablename__ = "bots"
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    description: Mapped[str] = mapped_column(Text, default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    name: Mapped[str] = mapped_column(String(120))
    draft: Mapped[dict] = mapped_column(JSON, default=dict)
    published_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    origins: Mapped[list] = mapped_column(JSON, default=list)


class Version(Record, Base):
    __tablename__ = "versions"
    bot_id: Mapped[str] = mapped_column(ForeignKey("bots.id"))
    number: Mapped[int] = mapped_column(Integer)
    flow: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("bot_id", "number"),)


class Conversation(Record, Base):
    __tablename__ = "conversations"
    bot_id: Mapped[str | None] = mapped_column(ForeignKey("bots.id"), nullable=True)
    version_id: Mapped[str | None] = mapped_column(
        ForeignKey("versions.id"), nullable=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    project_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_versions.id"), nullable=True
    )
    active_agent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_versions.id"), nullable=True
    )
    execution_mode: Mapped[str] = mapped_column(String(20), default="flow")
    status: Mapped[str] = mapped_column(String(20), default="bot")
    node_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    waiting: Mapped[bool] = mapped_column(Boolean, default=False)
    queue_id: Mapped[str | None] = mapped_column(ForeignKey("queues.id"), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    steps: Mapped[int] = mapped_column(Integer, default=0)
    queued_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    closed_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class Message(Record, Base):
    __tablename__ = "messages"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    client_id: Mapped[str] = mapped_column(String(100))
    sources: Mapped[list] = mapped_column(JSON, default=list)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("conversation_id", "role", "client_id"),)


class Event(Record, Base):
    __tablename__ = "events"
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class Job(Record, Base):
    __tablename__ = "jobs"
    kind: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (Index("jobs_pending", "status", "lease_until"),)


class Trace(Record, Base):
    __tablename__ = "traces"
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    node_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Tool(Record, Base):
    __tablename__ = "tools"
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(10), default="POST")
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    credential_id: Mapped[str | None] = mapped_column(
        ForeignKey("credentials.id"), nullable=True
    )
    timeout: Mapped[int] = mapped_column(Integer, default=15)
    safe_retry: Mapped[bool] = mapped_column(Boolean, default=False)


class Invocation(Record, Base):
    __tablename__ = "invocations"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.id"))
    invocation_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="started")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Collection(Record, Base):
    __tablename__ = "collections"
    bot_id: Mapped[str] = mapped_column(ForeignKey("bots.id"))
    name: Mapped[str] = mapped_column(String(120))
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.id"))
    generation: Mapped[int] = mapped_column(Integer, default=1)


class Document(Record, Base):
    __tablename__ = "documents"
    collection_id: Mapped[str] = mapped_column(ForeignKey("collections.id"))
    name: Mapped[str] = mapped_column(String(250))
    storage_key: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error: Mapped[str | None] = mapped_column(String(80), nullable=True)
    generation: Mapped[int] = mapped_column(Integer, default=1)


class Chunk(Record, Base):
    __tablename__ = "chunks"
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list] = mapped_column(JSON().with_variant(Vector(), "postgresql"))
    profile: Mapped[str] = mapped_column(String(200))


class AuthLimit(Base):
    __tablename__ = "auth_limits"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
