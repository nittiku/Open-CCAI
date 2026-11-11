#!/usr/bin/env python3
"""Baseline load probe for a disposable published bot. No model calls are hidden."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import statistics
import time
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--base", default="http://localhost:8080")
parser.add_argument("--bot", required=True)
parser.add_argument("--origin", required=True)
parser.add_argument("--conversations", type=int, default=20)
parser.add_argument("--concurrency", type=int, default=5)
args = parser.parse_args()
if not 1 <= args.conversations <= 10000 or not 1 <= args.concurrency <= 100:
    parser.error("Use 1–10000 conversations and 1–100 concurrent clients")


def probe(_):
    start = time.perf_counter()

    def req(path, body=None, token=None):
        headers = {"Origin": args.origin, "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = json.dumps(body).encode() if body is not None else None
        with urllib.request.urlopen(
            urllib.request.Request(
                args.base.rstrip("/") + "/api/v1" + path, data=data, headers=headers
            ),
            timeout=15,
        ) as r:
            return json.load(r)

    try:
        session = req("/widget/bots/" + args.bot + "/conversations", {})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            h = req(
                "/widget/conversations/" + session["conversation_id"],
                token=session["token"],
            )
            if h["messages"]:
                return time.perf_counter() - start
            time.sleep(0.25)
        return None
    except Exception:
        return None


started = time.perf_counter()
with ThreadPoolExecutor(args.concurrency) as pool:
    results = list(pool.map(probe, range(args.conversations)))
success = sorted(t for t in results if t is not None)
print(
    json.dumps(
        {
            "conversations": args.conversations,
            "concurrency": args.concurrency,
            "successful_greetings": len(success),
            "failed": results.count(None),
            "wall_seconds": round(time.perf_counter() - started, 3),
            "median_greeting_seconds": (
                round(statistics.median(success), 3) if success else None
            ),
            "p95_greeting_seconds": (
                round(success[min(len(success) - 1, int(len(success) * 0.95))], 3)
                if success
                else None
            ),
        },
        indent=2,
    )
)
raise SystemExit(0 if len(success) == len(results) else 1)
