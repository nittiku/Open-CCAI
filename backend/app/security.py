import hashlib
import ipaddress
import socket
import time
from urllib.parse import urlparse
import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy.orm import Session as DB
from .config import settings
from .db import session
from .models import User

passwords = PasswordHash.recommended()


def encrypt(value):
    return Fernet(settings.encryption_key.encode()).encrypt(value.encode()).decode()


def decrypt(value):
    return Fernet(settings.encryption_key.encode()).decrypt(value.encode()).decode()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def token(subject, kind, ttl=28800, **extra):
    return jwt.encode(
        {
            "sub": subject,
            "kind": kind,
            "iat": int(time.time()),
            "exp": int(time.time()) + ttl,
            **extra,
        },
        settings.secret,
        algorithm="HS256",
    )


def decode(value, kind):
    try:
        claims = jwt.decode(value, settings.secret, algorithms=["HS256"])
        if claims.get("kind") != kind:
            raise ValueError()
        return claims
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "Invalid or expired session")


def current_user(request: Request, db: DB = Depends(session)):
    value = request.cookies.get("ccai_session", "")
    if not value:
        raise HTTPException(401, "Sign in required")
    user = db.get(User, decode(value, "user")["sub"])
    if not user:
        raise HTTPException(401, "User no longer exists")
    return user


def roles(*allowed):
    def check(user=Depends(current_user)):
        if user.role not in allowed:
            raise HTTPException(403, "Role does not permit this action")
        return user

    return check


builders = roles("administrator", "builder")
operators = roles("administrator", "agent", "supervisor")
readers = roles("administrator", "builder", "agent", "supervisor")
admins = roles("administrator")


def public_origin(origin):
    parsed = urlparse(origin)
    return bool(
        parsed.scheme in ("http", "https")
        and parsed.netloc
        and not parsed.username
        and not parsed.password
        and parsed.path == ""
        and not parsed.query
        and not parsed.fragment
        and origin.rstrip("/") == f"{parsed.scheme}://{parsed.netloc}"
    )


def outbound_url(url, allowed_hosts):
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or host not in allowed_hosts
        or parsed.port not in (None, 443)
    ):
        raise ValueError(
            "Destination must be an explicitly allowed HTTPS host on port 443"
        )
    # Resolve on every call, disallowing internal addresses even on an allowed hostname.
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(
        not ipaddress.ip_address(a[4][0]).is_global for a in addresses
    ):
        raise ValueError("Destination resolves to a non-public address")
    return url
