#!/usr/bin/env python3
"""Generate local deployment secrets with the standard library; never print them."""

import base64
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent.parent
path = root / ".env"
values = {
    "POSTGRES_PASSWORD": secrets.token_hex(24),
    "RABBITMQ_USER": "ccai",
    "RABBITMQ_PASSWORD": secrets.token_hex(24),
    "APP_SECRET": secrets.token_hex(32),
    "ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
    "SETUP_TOKEN": secrets.token_urlsafe(32),
    "APP_ORIGINS": "http://localhost:8080,http://localhost:5173",
    "SECURE_COOKIE": "false",
    "TOOL_ALLOWED_HOSTS": "",
    "PROVIDER_ALLOWED_HOSTS": "api.openai.com,api.anthropic.com,generativelanguage.googleapis.com",
    "PORT": "8080",
}
try:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(".env already exists; left unchanged.")
with os.fdopen(fd, "w") as f:
    f.write(
        "# Local development. Configure HTTPS and SECURE_COOKIE=true for production.\n"
    )
    f.writelines(f"{key}={value}\n" for key, value in values.items())
print("Created .env (0600). Read SETUP_TOKEN locally to initialize the administrator.")
