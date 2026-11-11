import threading
import time
from celery import Celery
from sqlalchemy import select, or_, update
from .config import settings, validate_settings
from .db import Session
from .models import Job, AuthLimit, uid
from .runtime import execute_step, LEASE_SECONDS
from .knowledge import ingest

celery = Celery("open_ccai", broker=settings.broker_url)
celery.conf.update(
    task_ignore_result=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={"outbox": {"task": "ccai.dispatch", "schedule": 3.0}},
    task_serializer="json",
    accept_content=["json"],
    worker_hijack_root_logger=False,
    task_soft_time_limit=1740,
    task_time_limit=1800,
)


@celery.task(name="ccai.dispatch")
def dispatch():
    validate_settings()
    with Session() as db:
        ids = db.scalars(
            select(Job.id)
            .where(
                or_(
                    Job.status == "pending",
                    (Job.status == "running") & (Job.lease_until < time.time()),
                )
            )
            .order_by(Job.created)
            .limit(100)
        ).all()
        for job_id in ids:
            run.delay(job_id)
        # Bound authentication-rate bookkeeping retention.
        old_bucket = str(int(time.time() // 60) - 120)
        from sqlalchemy import delete

        db.execute(delete(AuthLimit).where(AuthLimit.id.like("%:" + old_bucket)))
        db.commit()


@celery.task(name="ccai.run")
def run(job_id):
    validate_settings()
    with Session() as db:
        job = db.get(Job, job_id)
        if not job:
            return
        kind = job.kind
    if kind == "conversation":
        execute_step(job_id)
        return
    with Session() as db:
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job.status == "done" or (
            job.status == "running" and job.lease_until > time.time()
        ):
            return
        job.status = "running"
        job.lease_token = uid()
        job.lease_until = time.time() + LEASE_SECONDS
        job.attempts += 1
        target, lease = job.target_id, job.lease_token
        db.commit()
    stop = threading.Event()

    def heartbeat():
        while not stop.wait(20):
            with Session() as db:
                db.execute(
                    update(Job)
                    .where(
                        Job.id == job_id,
                        Job.lease_token == lease,
                        Job.status == "running",
                    )
                    .values(lease_until=time.time() + LEASE_SECONDS)
                )
                db.commit()

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        if kind == "ingest":
            ingest(target)
        with Session() as db:
            db.execute(
                update(Job)
                .where(Job.id == job_id, Job.lease_token == lease)
                .values(status="done")
            )
            db.commit()
    finally:
        stop.set()
        thread.join(timeout=2)
