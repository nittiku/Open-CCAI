#!/usr/bin/env python3
"""Opt-in full deployment smoke test against a fresh installation, no paid APIs."""

import json
import os
from pathlib import Path
import secrets
import time
import urllib.request
import urllib.error
import http.cookiejar

root = Path(__file__).resolve().parent.parent
values = dict(
    line.strip().split("=", 1)
    for line in (root / ".env").read_text().splitlines()
    if line and not line.startswith("#")
)
base = os.getenv("SMOKE_BASE_URL", "http://localhost:" + values.get("PORT", "8080"))
client = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
)


def request(path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(
        base + "/api/v1" + path,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with client.open(r, timeout=10) as response:
        return json.load(response)


assert request("/health")["status"] == "ok"
assert not request("/auth/status")[
    "initialized"
], "Run smoke only against a fresh disposable installation"
password = secrets.token_urlsafe(24)
request(
    "/auth/setup",
    {
        "email": "smoke@example.test",
        "password": password,
        "setup_token": values["SETUP_TOKEN"],
    },
)
b = request("/bots", {"name": "Smoke bot", "origins": ["https://smoke.example"]})
request("/bots/" + b["id"] + "/publish", {})
s = request(
    "/widget/bots/" + b["id"] + "/conversations",
    {},
    headers={"Origin": "https://smoke.example"},
)
h = {"Origin": "https://smoke.example", "Authorization": "Bearer " + s["token"]}
path = "/widget/conversations/" + s["conversation_id"]
for _ in range(60):
    result = request(path, headers=h)
    if result["messages"]:
        break
    time.sleep(0.5)
assert result["messages"], "Worker failed to deliver greeting"
request(path + "/messages", {"content": "Please connect me", "client_id": "smoke-1"}, h)
for _ in range(60):
    result = request(path, headers=h)
    if result["status"] == "queued":
        break
    time.sleep(0.5)
assert result["status"] == "queued", "Worker failed to hand off"
request("/users/availability", {"available": True})
request("/conversations/" + s["conversation_id"] + "/claim", {})
request(
    "/conversations/" + s["conversation_id"] + "/messages",
    {"content": "An agent is here", "client_id": "smoke-agent-1"},
)
assert request(path, headers=h)["messages"][-1]["role"] == "agent"
request("/conversations/" + s["conversation_id"] + "/close", {})
assert request(path, headers=h)["status"] == "closed"
if os.getenv("SMOKE_STATE_PATH"):
    state = {
        "email": "smoke@example.test",
        "password": password,
        "conversation_id": s["conversation_id"],
    }
    fd = os.open(
        os.environ["SMOKE_STATE_PATH"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    with os.fdopen(fd, "w") as stream:
        json.dump(state, stream)
print(
    "Full deployment smoke passed: initialize → publish → widget → worker → handoff → claim → reply → close"
)
