from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator

Role = Literal["administrator", "builder", "agent", "supervisor"]


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=256)

    @field_validator("email")
    @classmethod
    def email_normalize(cls, value):
        if "@" not in value:
            raise ValueError("Email address required")
        return value.strip().lower()


class Setup(Login):
    setup_token: str


class Invite(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: Role


class Accept(Login):
    invitation_token: str


class CredentialIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    secret: str = Field(min_length=1, max_length=10000)


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["openai", "anthropic", "gemini", "compatible"]
    model: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:/-]+$")
    purpose: Literal["generation", "embedding"] = "generation"
    credential_id: str
    base_url: str | None = None
    capabilities: dict[str, bool] = Field(default_factory=dict)
    pricing: dict[str, float] = Field(default_factory=dict)


class Named(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class BotIn(Named):
    project_id: str | None = None
    description: str = Field(default="", max_length=5000)
    purpose: str = Field(default="", max_length=5000)
    origins: list[str] = Field(default_factory=list, max_length=30)


class DraftIn(BaseModel):
    flow: dict[str, Any]


class WidgetStart(BaseModel):
    test: bool = False


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=16000)
    client_id: str = Field(min_length=1, max_length=100)


class ToolIn(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
    description: str = Field(default="", max_length=2000)
    url: str = Field(max_length=2000)
    method: Literal["GET", "POST"] = "POST"
    input_schema: dict = Field(default_factory=lambda: {"type": "object"})
    output_schema: dict = Field(default_factory=lambda: {"type": "object"})
    credential_id: str | None = None
    timeout: int = Field(default=15, ge=1, le=30)
    safe_retry: bool = False


class CollectionIn(Named):
    bot_id: str
    provider_id: str


class ReindexIn(BaseModel):
    provider_id: str | None = None


class ImportIn(BaseModel):
    project_id: str | None = None
    agent_bindings: dict[str, str] = Field(default_factory=dict)
    bundle: dict
    provider_bindings: dict[str, str] = Field(default_factory=dict)
    tool_bindings: dict[str, str] = Field(default_factory=dict)
    queue_bindings: dict[str, str] = Field(default_factory=dict)


class OrchestratorIn(BaseModel):
    provider_id: str | None = None
    description: str = Field(default="", max_length=5000)
    purpose: str = Field(default="", max_length=5000)
    instructions: str = Field(default="", max_length=20000)
    welcome: str = Field(default="Hello! What can I help you with?", max_length=16000)
    flow_ids: list[str] = Field(default_factory=list, max_length=100)
    agent_ids: list[str] = Field(default_factory=list, max_length=100)
    fallback_queue_id: str | None = None


class ProjectIn(Named):
    description: str = Field(default="", max_length=5000)
    purpose: str = Field(default="", max_length=5000)
    origins: list[str] = Field(default_factory=list, max_length=30)
    orchestrator: OrchestratorIn = Field(default_factory=OrchestratorIn)


class AgentDefinition(BaseModel):
    provider_id: str | None = None
    instructions: str = Field(default="", max_length=20000)
    tool_ids: list[str] = Field(default_factory=list, max_length=8)
    collection_ids: list[str] = Field(default_factory=list, max_length=8)
    max_iterations: int = Field(default=8, ge=1, le=16)
    output_schema: dict | None = None


class AgentIn(Named):
    project_id: str
    description: str = Field(default="", max_length=5000)
    purpose: str = Field(default="", max_length=5000)
    definition: AgentDefinition = Field(default_factory=AgentDefinition)
