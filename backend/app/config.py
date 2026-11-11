import os
from dataclasses import dataclass
from cryptography.fernet import Fernet


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://ccai:ccai@localhost/ccai"
    )
    broker_url: str = os.getenv("BROKER_URL", "amqp://guest:guest@localhost:5672//")
    secret: str = os.getenv("APP_SECRET", "")
    encryption_key: str = os.getenv("ENCRYPTION_KEY", "")
    setup_token: str = os.getenv("SETUP_TOKEN", "")
    origins: tuple = tuple(
        x.strip()
        for x in os.getenv(
            "APP_ORIGINS", "http://localhost:8080,http://localhost:5173"
        ).split(",")
    )
    secure_cookie: bool = os.getenv("SECURE_COOKIE", "true").lower() == "true"
    storage_path: str = os.getenv("STORAGE_PATH", "./data/uploads")
    tool_hosts: tuple = tuple(
        x.strip() for x in os.getenv("TOOL_ALLOWED_HOSTS", "").split(",") if x.strip()
    )
    provider_hosts: tuple = tuple(
        x.strip()
        for x in os.getenv(
            "PROVIDER_ALLOWED_HOSTS",
            "api.openai.com,api.anthropic.com,generativelanguage.googleapis.com",
        ).split(",")
        if x.strip()
    )


settings = Settings()


def validate_settings():
    if len(settings.secret) < 32 or len(settings.setup_token) < 24:
        raise RuntimeError(
            "Set APP_SECRET (32+ characters) and SETUP_TOKEN (24+ characters)"
        )
    Fernet(settings.encryption_key.encode())
