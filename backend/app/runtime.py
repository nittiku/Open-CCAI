"""Durable bounded steps. Database leases are the authority; Celery only delivers hints."""

import json
import time
import threading
from jsonschema import Draft202012Validator
from sqlalchemy import select, or_
from .db import Session
from .models import (
    Conversation,
    Version,
    Message,
    Job,
    Trace,
    Event,
    Provider,
    Tool,
    uid,
    AgentVersion,
    ProjectVersion,
)
from .flows import next_node, render
from .knowledge import retrieve
from . import providers
from .tools import call_tool
from .agent_execution import run_agent
from .orchestration import route

MAX_STEPS = 200
LEASE_SECONDS = 180


def emit(db, conversation_id, kind, payload):
    db.add(Event(conversation_id=conversation_id, kind=kind, payload=payload))


def enqueue(db, kind, target_id):
    db.add(Job(kind=kind, target_id=target_id))


def add_message(db, conversation_id, role, content, client_id=None, sources=None):
    row = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        client_id=client_id or uid(),
        sources=sources or [],
    )
    db.add(row)
    db.flush()
    emit(
        db,
        conversation_id,
        "message",
        {"id": row.id, "role": role, "content": content, "sources": row.sources},
    )
    return row


def snapshot_step(job_id):
    with Session() as db:
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if (
            not job
            or job.status == "done"
            or (job.status == "running" and job.lease_until > time.time())
        ):
            return None
        if job.kind != "conversation":
            return None
        conv = db.scalar(
            select(Conversation)
            .where(Conversation.id == job.target_id)
            .with_for_update()
        )
        if not conv or conv.status != "bot":
            job.status = "done"
            db.commit()
            return None
        active = db.scalar(
            select(Job).where(
                Job.target_id == conv.id,
                Job.id != job.id,
                Job.status == "running",
                Job.lease_until > time.time(),
            )
        )
        if active:
            return None
        if conv.steps >= MAX_STEPS:
            conv.status = "error"
            db.add(
                Trace(
                    conversation_id=conv.id,
                    node_id=conv.node_id or "",
                    status="error",
                    detail={"code": "step_limit"},
                )
            )
            emit(db, conv.id, "state", {"status": "error"})
            job.status = "done"
            db.commit()
            return None
        if not conv.node_id:
            job.status = "done"
            db.commit()
            return None
        job.status, job.lease_until, job.lease_token = (
            "running",
            time.time() + LEASE_SECONDS,
            uid(),
        )
        job.attempts += 1
        project_snapshot = (
            db.get(ProjectVersion, conv.project_version_id).snapshot
            if conv.project_version_id
            else None
        )
        flow = {"nodes": [], "edges": []}
        if conv.execution_mode == "orchestrator":
            node = {"id": "orchestrator", "type": "orchestrator", "config": {}}
        elif conv.execution_mode == "agent":
            node = {
                "id": "agent",
                "type": "agent",
                "config": {"agent_version_id": conv.active_agent_version_id},
            }
        else:
            flow = db.get(Version, conv.version_id).flow
            node = next((n for n in flow["nodes"] if n["id"] == conv.node_id), None)
        if not node:
            conv.status = "error"
            job.status = "done"
            db.commit()
            return None
        data = {
            "job_id": job.id,
            "lease": job.lease_token,
            "conversation_id": conv.id,
            "revision": conv.revision,
            "step": conv.steps,
            "node": node,
            "flow": flow,
            "variables": dict(conv.variables),
            "bot_id": conv.bot_id,
            "project_id": conv.project_id,
            "project_snapshot": project_snapshot,
            "execution_mode": conv.execution_mode,
        }
        if node["type"] in ("input", "orchestrator"):
            message = db.scalar(
                select(Message)
                .where(
                    Message.conversation_id == conv.id,
                    Message.role == "customer",
                    Message.consumed == False,
                )
                .order_by(Message.created, Message.id)
                .with_for_update()
            )
            if not message:
                if node["type"] != "orchestrator" or conv.steps > 0:
                    conv.waiting = True
                    job.status = "done"
                    db.commit()
                    return None
            else:
                data["input_id"], data["input"] = message.id, message.content
        boundary = None
        if node["type"] == "orchestrator" and data.get("input_id"):
            boundary = db.get(Message, data["input_id"])
        elif conv.execution_mode == "agent" and conv.variables.get(
            "__routing_message_id"
        ):
            boundary = db.get(Message, conv.variables["__routing_message_id"])
        statement = select(Message).where(
            Message.conversation_id == conv.id, Message.role.in_(["customer", "bot"])
        )
        if boundary and boundary.conversation_id == conv.id:
            statement = statement.where(
                or_(
                    Message.created < boundary.created,
                    (Message.created == boundary.created) & (Message.id <= boundary.id),
                )
            )
        data["messages"] = [
            {
                "role": "user" if m.role == "customer" else "assistant",
                "content": m.content,
            }
            for m in db.scalars(statement.order_by(Message.created, Message.id)).all()
        ][-40:]
        db.commit()
        return data


def stream_chunk(data, text):
    with Session() as db:
        conv = db.scalar(
            select(Conversation)
            .where(Conversation.id == data["conversation_id"])
            .with_for_update()
        )
        job = db.get(Job, data["job_id"])
        if (
            conv.status != "bot"
            or conv.revision != data["revision"]
            or job.lease_token != data["lease"]
        ):
            raise providers.ProviderError("execution_cancelled")
        emit(
            db,
            conv.id,
            "chunk",
            {"text": text, "response_id": data["lease"], "step": data["step"]},
        )
        db.commit()


def compute(data):
    node, variables = data["node"], data["variables"]
    cfg, kind = node.get("config", {}), node["type"]
    result = {"branch": "next", "variables": {}, "sources": [], "usage": []}
    if kind == "orchestrator":
        return route(data)
    if kind == "message":
        result["text"] = str(render(cfg["text"], variables))
    elif kind == "input":
        result["variables"][cfg["variable"]] = data["input"]
    elif kind == "variable":
        result["variables"][cfg["variable"]] = render(cfg["value"], variables)
    elif kind == "condition":
        result["branch"] = (
            "true" if variables.get(cfg["variable"]) == cfg["equals"] else "false"
        )
    elif kind == "handoff":
        result["status"], result["queue_id"] = "queued", cfg.get("queue_id") or None
    elif kind == "end":
        result["status"] = "closed"
    elif kind == "tool":
        with Session() as db:
            tool = db.get(Tool, cfg["tool_id"])
            output = call_tool(
                tool,
                render(cfg.get("arguments", {}), variables),
                data["conversation_id"],
                f"{data['conversation_id']}:{data['step']}:tool",
            )
            result["variables"][cfg.get("variable", "tool_result")] = output
    elif kind == "knowledge":
        with Session() as db:
            result["sources"] = retrieve(
                db,
                data["bot_id"],
                cfg.get("collection_ids", []),
                str(render(cfg.get("query", "${question}"), variables)),
            )
            result["variables"][cfg.get("variable", "knowledge")] = result["sources"]
    elif kind in ("ai", "agent"):
        if kind == "agent":
            with Session() as db:
                version = db.get(AgentVersion, cfg.get("agent_version_id"))
                if not version:
                    raise ValueError("agent_version_missing")
                cfg = version.definition
        return run_agent(
            data, cfg, lambda text: stream_chunk(data, text), tool_executor=call_tool
        )

    return result


def execute_step(job_id):
    data = snapshot_step(job_id)
    if not data:
        return
    error = None
    stop = threading.Event()

    def heartbeat():
        from sqlalchemy import update

        while not stop.wait(20):
            with Session() as db:
                db.execute(
                    update(Job)
                    .where(
                        Job.id == job_id,
                        Job.lease_token == data["lease"],
                        Job.status == "running",
                    )
                    .values(lease_until=time.time() + LEASE_SECONDS)
                )
                db.commit()

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        result = compute(data)
    except Exception as exc:
        code = (
            exc.code
            if isinstance(exc, providers.ProviderError)
            else (
                str(exc)
                if str(exc)
                in {
                    "tool_outcome_uncertain",
                    "tool_failed",
                    "foreign_collection",
                    "embedding_dimension_changed_reindex_required",
                }
                else "node_execution_failed"
            )
        )
        error, result = code, {
            "branch": "error",
            "variables": {"error": code},
            "sources": [],
            "usage": [],
        }
    finally:
        stop.set()
        thread.join(timeout=2)
    if error and data["execution_mode"] in ("orchestrator", "agent"):
        result.update(
            status="queued",
            queue_id=data["project_snapshot"]["orchestrator"].get("fallback_queue_id"),
        )
    with Session() as db:
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job.lease_token != data["lease"]:
            return
        conv = db.scalar(
            select(Conversation)
            .where(Conversation.id == data["conversation_id"])
            .with_for_update()
        )
        if (
            conv.status != "bot"
            or conv.revision != data["revision"]
            or conv.steps != data["step"]
        ):
            job.status = "done"
            db.commit()
            return
        branch = result["branch"]
        next_id = next_node(data["flow"], conv.node_id, branch)
        db.add(
            Trace(
                conversation_id=conv.id,
                node_id=conv.node_id,
                status="error" if error else "succeeded",
                detail={
                    "code": error,
                    "usage": result["usage"],
                    "route": result.get("route"),
                    "sources": [
                        {k: v for k, v in s.items() if k != "text"}
                        for s in result["sources"]
                    ],
                },
            )
        )
        if result.get("text"):
            add_message(
                db,
                conv.id,
                "bot",
                result["text"],
                f"step:{conv.steps}",
                [
                    {k: v for k, v in s.items() if k != "text"}
                    for s in result["sources"]
                ],
            )
        conv.variables = {**conv.variables, **result["variables"]}
        if data.get("input_id"):
            db.get(Message, data["input_id"]).consumed = True
        conv.steps += 1
        conv.waiting = False
        conv.node_id = next_id
        decision = result.get("route")
        if decision:
            conv.revision += 1
            conv.waiting = False
            if decision["target_type"] == "flow":
                conv.execution_mode = "flow"
                conv.bot_id, conv.version_id = (
                    decision["target_id"],
                    decision["version_id"],
                )
                conv.active_agent_version_id = None
                conv.node_id = db.get(Version, conv.version_id).flow["entry"]
            else:
                conv.execution_mode = "agent"
                conv.bot_id = conv.version_id = None
                conv.active_agent_version_id = decision["version_id"]
                conv.node_id = "agent"
        elif data["execution_mode"] == "orchestrator" and not result.get("status"):
            conv.node_id = "orchestrator"
            conv.waiting = True
        elif conv.project_version_id and (
            result.get("status") == "closed"
            or (not next_id and not result.get("status"))
        ):
            if error:
                result.update(
                    status="queued",
                    queue_id=data["project_snapshot"]["orchestrator"].get(
                        "fallback_queue_id"
                    ),
                )
            else:
                result.pop("status", None)
                conv.execution_mode = "orchestrator"
                conv.bot_id = conv.version_id = conv.active_agent_version_id = None
                conv.node_id = "orchestrator"
        if result.get("status"):
            conv.status = result["status"]
            conv.revision += 1
            if conv.status == "queued":
                conv.queue_id = result.get("queue_id")
                conv.queued_at = time.time()
            if conv.status == "closed":
                conv.closed_at = time.time()
            emit(db, conv.id, "state", {"status": conv.status})
        elif not conv.node_id:
            conv.status = "error" if error else "closed"
            conv.closed_at = time.time() if not error else None
            emit(db, conv.id, "state", {"status": conv.status})
        if conv.status == "bot" and conv.node_id and not conv.waiting:
            enqueue(db, "conversation", conv.id)
        elif conv.status == "bot" and conv.waiting:
            db.flush()
            if db.scalar(
                select(Message.id)
                .where(
                    Message.conversation_id == conv.id,
                    Message.role == "customer",
                    Message.consumed == False,
                )
                .limit(1)
            ):
                enqueue(db, "conversation", conv.id)
        job.status = "done"
        emit(
            db,
            conv.id,
            "step",
            {
                "node_id": data["node"]["id"],
                "error": error,
                "response_id": data["lease"],
                "step": data["step"],
            },
        )
        db.commit()
