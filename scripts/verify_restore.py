#!/usr/bin/env python3
"""Verify the smoke conversation survived a fresh Docker restore (CI only)."""

import http.cookiejar
import json
import os
from pathlib import Path
import sys
import urllib.request

state = json.loads(Path(sys.argv[1]).read_text())
root = Path(__file__).resolve().parent.parent
values = dict(
    line.split("=", 1)
    for line in (root / ".env").read_text().splitlines()
    if line and not line.startswith("#")
)
base = os.getenv("SMOKE_BASE_URL", "http://localhost:" + values.get("PORT", "8080"))
client = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
)


def request(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    with client.open(
        urllib.request.Request(
            base + "/api/v1" + path,
            data=data,
            headers={"Content-Type": "application/json"},
        ),
        timeout=10,
    ) as r:
        return json.load(r)


request("/auth/login", {"email": state["email"], "password": state["password"]})
conversation = request("/conversations/" + state["conversation_id"])
assert conversation["status"] == "closed"
assert any(
    m["role"] == "agent" and m["content"] == "An agent is here"
    for m in conversation["messages"]
)
assert request("/monitoring")["handoffs"] == 1
print(
    "Restored administrator login, closed transcript, human reply, and handoff metrics verified."
)
