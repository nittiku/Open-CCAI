#!/usr/bin/env python3
"""Local-only SQLite development API or polling worker. Production uses Compose."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "backend"))
from dotenv import load_dotenv

load_dotenv(root / ".env")
os.environ.setdefault(
    "DATABASE_URL", "sqlite:///" + str(root / "data" / "development.db")
)
os.environ.setdefault("SECURE_COOKIE", "false")
os.environ.setdefault("STORAGE_PATH", str(root / "data" / "uploads"))
(root / "data").mkdir(exist_ok=True)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("process", choices=["api", "worker", "migrate"])
args = parser.parse_args()
if args.process == "migrate":
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=root / "backend",
        check=True,
    )
elif args.process == "api":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, access_log=False)
else:
    from app.config import validate_settings
    from app.db import Session
    from app.models import Job
    from app.worker import run
    from sqlalchemy import select, or_

    validate_settings()
    print(
        "Local polling worker. SQLite is for development only; use PostgreSQL for deployment."
    )
    while True:
        with Session() as db:
            ids = db.scalars(
                select(Job.id)
                .where(
                    or_(
                        Job.status == "pending",
                        (Job.status == "running") & (Job.lease_until < time.time()),
                    )
                )
                .limit(50)
            ).all()
        for job_id in ids:
            run(job_id)
        time.sleep(0.5)
