import json
import re
from jsonschema import Draft202012Validator
from sqlalchemy import select
from .models import Provider, Tool, Queue, Collection, Agent, Bot

KINDS = {
    "message",
    "input",
    "condition",
    "variable",
    "tool",
    "knowledge",
    "ai",
    "agent",
    "handoff",
    "end",
}


def default_flow(queue_id=None):
    return {
        "schema_version": 1,
        "entry": "welcome",
        "nodes": [
            {
                "id": "welcome",
                "type": "message",
                "position": {"x": 60, "y": 80},
                "config": {"text": "Hello! How can we help?"},
            },
            {
                "id": "question",
                "type": "input",
                "position": {"x": 340, "y": 80},
                "config": {"variable": "question"},
            },
            {
                "id": "transfer",
                "type": "handoff",
                "position": {"x": 620, "y": 80},
                "config": {"queue_id": queue_id},
            },
        ],
        "edges": [
            {"id": "e1", "source": "welcome", "target": "question", "label": "next"},
            {"id": "e2", "source": "question", "target": "transfer", "label": "next"},
        ],
    }


def validate_flow(flow, db=None, bot_id=None):
    errors = []
    if not isinstance(flow, dict) or flow.get("schema_version") != 1:
        return ["Expected workflow schema_version 1"]
    nodes, edges = flow.get("nodes"), flow.get("edges")
    if (
        not isinstance(nodes, list)
        or not nodes
        or len(nodes) > 200
        or not isinstance(edges, list)
        or len(edges) > 600
    ):
        return ["Workflow requires 1–200 nodes and at most 600 edges"]
    if any(
        not isinstance(n, dict)
        or not isinstance(n.get("id"), str)
        or not n["id"]
        or len(n["id"]) > 100
        or not isinstance(n.get("config", {}), dict)
        for n in nodes
    ):
        return ["Each node needs a short string id and an object config"]
    ids = {n["id"] for n in nodes}
    if len(ids) != len(nodes):
        errors.append("Node IDs must be unique")
    if not isinstance(flow.get("entry"), str) or flow.get("entry") not in ids:
        return errors + ["Entry node does not exist"]
    if any(
        not isinstance(e, dict)
        or any(not isinstance(e.get(k), str) for k in ("source", "target"))
        or not isinstance(e.get("label", "next"), str)
        for e in edges
    ):
        return errors + ["Edges need string source, target, and branch labels"]
    seen = set()
    for edge in edges:
        if not isinstance(edge, dict):
            errors.append("Edges must be objects")
            continue
        key = (edge.get("source"), edge.get("label", "next"))
        if edge.get("source") not in ids or edge.get("target") not in ids:
            errors.append("Edge references a missing node")
        if key in seen:
            errors.append(f"Duplicate outgoing branch {key}")
        seen.add(key)
    for node in nodes:
        kind, cfg, nid = node.get("type"), node.get("config", {}), node["id"]
        if not isinstance(kind, str) or kind not in KINDS:
            errors.append(f"{nid}: unsupported node type")
            continue
        required = {
            "message": ["text"],
            "input": ["variable"],
            "variable": ["variable", "value"],
            "condition": ["variable", "equals"],
            "tool": ["tool_id"],
            "knowledge": ["collection_ids"],
            "ai": ["provider_id"],
            "agent": ["agent_id"],
            "handoff": [],
            "end": [],
        }[kind]
        for field in required:
            if field not in cfg:
                errors.append(f"{nid}: missing {field}")
        for field in (
            "text",
            "instructions",
            "query",
            "provider_id",
            "agent_id",
            "tool_id",
            "variable",
        ):
            if field in cfg and (
                not isinstance(cfg[field], str)
                or len(cfg[field])
                > (20000 if field in ("text", "instructions", "query") else 120)
            ):
                errors.append(f"{nid}: invalid {field}")
        if "variable" in cfg and (
            not isinstance(cfg["variable"], str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", cfg["variable"])
        ):
            errors.append(
                f"{nid}: variable must be an identifier of at most 64 characters"
            )
        if "arguments" in cfg and not isinstance(cfg["arguments"], dict):
            errors.append(f"{nid}: arguments must be an object")
        if cfg.get("queue_id") is not None and not isinstance(cfg["queue_id"], str):
            errors.append(f"{nid}: invalid queue_id")
        for field in ("collection_ids", "tool_ids"):
            if field in cfg and (
                not isinstance(cfg[field], list)
                or len(cfg[field]) > 8
                or any(not isinstance(x, str) for x in cfg[field])
            ):
                errors.append(f"{nid}: {field} must be a list of IDs")
        branches = (
            ["true", "false"]
            if kind == "condition"
            else ([] if kind in ("end", "handoff") else ["next"])
        )
        if kind in ("ai", "agent", "tool", "knowledge"):
            branches.append("error")
        for branch in branches:
            if (nid, branch) not in seen:
                errors.append(f"{nid}: connect the {branch} branch")
        if kind == "ai" and (
            not isinstance(cfg.get("max_iterations", 4), int)
            or not 1 <= cfg.get("max_iterations", 4) <= 8
        ):
            errors.append(f"{nid}: max_iterations must be 1–8")
        if cfg.get("output_schema") is not None:
            try:
                Draft202012Validator.check_schema(cfg["output_schema"])
            except Exception:
                errors.append(f"{nid}: invalid output schema")
        if not db or errors:
            continue
        for field, model in (
            ("provider_id", Provider),
            ("tool_id", Tool),
            ("queue_id", Queue),
        ):
            if cfg.get(field) and not db.get(model, cfg[field]):
                errors.append(f"{nid}: missing {field}")
        for field, model in (("tool_ids", Tool), ("collection_ids", Collection)):
            if not isinstance(cfg.get(field, []), list):
                continue
            for rid in cfg.get(field, []):
                row = db.get(model, rid) if isinstance(rid, str) else None
                if not row or (model is Collection and row.bot_id != bot_id):
                    errors.append(f"{nid}: invalid or foreign {field}")
        if kind == "agent":
            agent = db.get(Agent, cfg.get("agent_id")) if cfg.get("agent_id") else None
            bot = db.get(Bot, bot_id)
            if (
                not agent
                or not bot
                or agent.project_id != bot.project_id
                or not agent.published_id
            ):
                errors.append(f"{nid}: select a published agent from this project")
        if kind == "ai" and cfg.get("provider_id"):
            p = db.get(Provider, cfg["provider_id"])
            if p:
                if p.purpose != "generation":
                    errors.append(f"{nid}: generation provider required")
                if cfg.get("tool_ids") and not p.capabilities.get("tools"):
                    errors.append(f"{nid}: provider has no tool capability")
                if cfg.get("output_schema") and not p.capabilities.get("structured"):
                    errors.append(
                        f"{nid}: provider has no structured-output capability"
                    )
    # Unreachable nodes almost always indicate a disconnected canvas.
    reachable, todo = set(), [flow.get("entry")]
    while todo:
        current = todo.pop()
        if current in reachable:
            continue
        reachable.add(current)
        todo.extend(
            e.get("target")
            for e in edges
            if isinstance(e, dict) and e.get("source") == current
        )
    if ids - reachable:
        errors.append("Workflow contains unreachable nodes")
    return errors


def next_node(flow, node_id, branch="next"):
    return next(
        (
            e["target"]
            for e in flow["edges"]
            if e["source"] == node_id and e.get("label", "next") == branch
        ),
        None,
    )


def render(value, variables):
    if isinstance(value, str):
        exact = re.fullmatch(r"\$\{([A-Za-z0-9_]+)\}", value)
        if exact:
            return variables.get(exact[1], "")
        return re.sub(
            r"\$\{([A-Za-z0-9_]+)\}", lambda m: str(variables.get(m[1], "")), value
        )
    if isinstance(value, dict):
        return {k: render(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, variables) for v in value]
    return value
