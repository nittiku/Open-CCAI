#!/usr/bin/env python3
"""Start the isolated local playground; never uses DATABASE_URL or production secrets."""

import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "backend"))


def configure_environment():
    folder = root / "data" / "demo"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    keyfile = folder / "secrets.json"
    if not keyfile.exists():
        values = {
            "APP_SECRET": secrets.token_hex(32),
            "ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
            "SETUP_TOKEN": secrets.token_urlsafe(32),
        }
        try:
            fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as stream:
                json.dump(values, stream)
    values = json.loads(keyfile.read_text())
    os.environ.update(values)
    os.environ.update(
        DATABASE_URL="sqlite:///" + str(folder / "demo.db"),
        STORAGE_PATH=str(folder / "uploads"),
        SECURE_COOKIE="false",
        APP_ORIGINS=os.getenv(
            "CCAI_DEMO_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ),
        LITELLM_LOCAL_MODEL_COST_MAP="True",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("process", choices=["api", "worker"])
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    configure_environment()
    from app import providers, runtime
    from app.demo import DemoAdapter, demo_tool_executor, seed_demo

    providers.adapter = DemoAdapter(providers.adapter)
    runtime.call_tool = demo_tool_executor
    if args.process == "api":
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=root / "backend",
            check=True,
        )
        from app.db import Session

        with Session() as db:
            seed_demo(db)
        import uvicorn

        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, access_log=False)
    else:
        from app.db import Session
        from app.models import Job
        from app.worker import run
        from sqlalchemy import select, or_

        try:
            while True:
                with Session() as db:
                    ids = list(
                        db.scalars(
                            select(Job.id)
                            .where(
                                or_(
                                    Job.status == "pending",
                                    (Job.status == "running")
                                    & (Job.lease_until < time.time()),
                                )
                            )
                            .order_by(Job.created)
                            .limit(50)
                        )
                    )
                for jid in ids:
                    run(jid)
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
