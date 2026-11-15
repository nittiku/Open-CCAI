"""Project orchestration and independently published full agents."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select, func, text, update
from sqlalchemy.orm import Session as DB
from .db import session, engine
from .models import (
    Project,
    ProjectVersion,
    Agent,
    AgentVersion,
    Bot,
    Version,
    Collection,
    Document,
    Chunk,
    Tool,
    Invocation,
    Provider,
    Queue,
    Conversation,
)
from .schemas import ProjectIn, AgentIn
from .security import builders, public_origin, token
from .orchestration import project_snapshot, validate_agent
from .runtime import enqueue, emit

router = APIRouter(prefix="/api/v1")


def require(db, model, rid):
    row = db.get(model, rid)
    if not row:
        raise HTTPException(404, "Record not found")
    return row


def project_view(p):
    return {
        key: getattr(p, key)
        for key in (
            "id",
            "name",
            "description",
            "purpose",
            "origins",
            "orchestrator",
            "published_id",
        )
    }


def agent_view(a):
    return {
        key: getattr(a, key)
        for key in (
            "id",
            "project_id",
            "name",
            "description",
            "purpose",
            "draft",
            "published_id",
        )
    }


def sequence(db, model, owner_field, owner_id, testing=False):
    column = getattr(model, owner_field)
    if testing:
        return (
            db.scalar(
                select(func.min(model.number)).where(
                    column == owner_id, model.number < 0
                )
            )
            or 0
        ) - 1
    return (
        db.scalar(
            select(func.max(model.number)).where(column == owner_id, model.number > 0)
        )
        or 0
    ) + 1


def open_project_conversation(db, project, version, origin):
    c = Conversation(
        project_id=project.id,
        project_version_id=version.id,
        execution_mode="orchestrator",
        node_id="orchestrator",
    )
    db.add(c)
    db.flush()
    enqueue(db, "conversation", c.id)
    emit(db, c.id, "state", {"status": "bot"})
    db.commit()
    return {
        "conversation_id": c.id,
        "token": token(c.id, "widget", 86400, project_id=project.id, origin=origin),
    }


@router.get("/projects")
def projects(user=Depends(builders), db: DB = Depends(session)):
    return [
        project_view(p) for p in db.scalars(select(Project).order_by(Project.created))
    ]


def _unique_tool_name(db: DB, base: str, suffix: str) -> str:
    if not db.scalar(select(Tool.id).where(Tool.name == base)):
        return base
    candidate = f"{base[:56]}_{suffix}"
    if not db.scalar(select(Tool.id).where(Tool.name == candidate)):
        return candidate
    idx = 2
    while db.scalar(select(Tool.id).where(Tool.name == f"{candidate[:54]}_{idx}")):
        idx += 1
    return f"{candidate[:54]}_{idx}"


def _sample_flow(
    name: str,
    description: str,
    purpose: str,
    project_id: str,
    nodes: list[dict],
    edges: list[dict],
) -> Bot:
    return Bot(
        project_id=project_id,
        name=name,
        description=description,
        purpose=purpose,
        origins=[],
        draft={
            "schema_version": 1,
            "entry": nodes[0]["id"],
            "nodes": nodes,
            "edges": edges,
        },
    )


def _apply_project_template(db: DB, project: Project, template: str) -> None:
    if template == "blank":
        return
    suffix = project.id[:6]
    chat = db.scalar(
        select(Provider)
        .where(Provider.purpose == "generation")
        .order_by(Provider.created)
    )
    queue = db.scalar(select(Queue).order_by(Queue.created))
    chat_id = chat.id if chat else None
    queue_id = queue.id if queue else None

    if template == "support":
        tool_specs = [
            (
                "lookup_ticket",
                "Look up a customer support ticket by ID (template dummy tool).",
                "https://example.com/api/tickets",
                "GET",
                {
                    "type": "object",
                    "properties": {"ticket_id": {"type": "string"}},
                    "required": ["ticket_id"],
                },
            ),
            (
                "create_ticket",
                "Create a new customer support ticket (template dummy tool).",
                "https://example.com/api/tickets",
                "POST",
                {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string"},
                        "subject": {"type": "string"},
                    },
                    "required": ["email", "subject"],
                },
            ),
        ]
        agent_spec = (
            "Support specialist",
            "Triage customer issues and manage support tickets.",
            "Use for general support questions, troubleshooting, and ticket updates.",
            "You are a helpful customer support specialist. Use lookup_ticket or create_ticket when needed, and escalate to a human agent if the issue requires manual review.",
        )
        welcome_text = "Hi! Welcome to support. How can I help you today?"
    else:
        tool_specs = [
            (
                "lookup_order",
                "Look up an order status by order ID (template dummy tool).",
                "https://example.com/api/orders",
                "GET",
                {
                    "type": "object",
                    "properties": {"order_id": {"type": "string"}},
                    "required": ["order_id"],
                },
            ),
            (
                "start_return",
                "Initiate a product return request (template dummy tool).",
                "https://example.com/api/returns",
                "POST",
                {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["order_id", "reason"],
                },
            ),
        ]
        agent_spec = (
            "Orders specialist",
            "Check order status, shipping updates, and return eligibility.",
            "Use for order tracking, delivery, and return requests.",
            "You are an orders and returns specialist. Ask for an order ID, then use lookup_order or start_return to assist the customer.",
        )
        welcome_text = "Hello! I can help you track an order or start a return."

    tools: list[Tool] = []
    for base_name, desc, url, method, schema in tool_specs:
        t = Tool(
            name=_unique_tool_name(db, base_name, suffix),
            description=desc,
            url=url,
            method=method,
            input_schema=schema,
            safe_retry=method == "GET",
        )
        db.add(t)
        tools.append(t)
    db.flush()

    agent = Agent(
        project_id=project.id,
        name=agent_spec[0],
        description=agent_spec[1],
        purpose=agent_spec[2],
        draft={
            "provider_id": chat_id,
            "instructions": agent_spec[3],
            "tool_ids": [t.id for t in tools],
            "collection_ids": [],
            "max_iterations": 4,
            "output_schema": None,
        },
    )
    db.add(agent)
    db.flush()

    primary_tool = tools[0]
    if template == "support":
        flow1 = _sample_flow(
            "Quick triage",
            "Greet the customer and collect their question.",
            "Use for initial greeting and collecting support details.",
            project.id,
            [
                {
                    "id": "welcome",
                    "type": "message",
                    "position": {"x": 200, "y": 60},
                    "config": {"text": welcome_text},
                },
                {
                    "id": "ask",
                    "type": "input",
                    "position": {"x": 200, "y": 210},
                    "config": {
                        "prompt": "What is your ticket ID or question?",
                        "variable": "ticket_id",
                    },
                },
                {
                    "id": "lookup",
                    "type": "tool",
                    "position": {"x": 200, "y": 360},
                    "config": {
                        "tool_id": primary_tool.id,
                        "args": {"ticket_id": "{{ticket_id}}"},
                        "save_as": "ticket_result",
                    },
                },
                {
                    "id": "done",
                    "type": "end",
                    "position": {"x": 200, "y": 510},
                    "config": {"text": "Thanks! Let us know if you need anything else."},
                },
            ],
            [
                {"id": "e1", "source": "welcome", "target": "ask"},
                {"id": "e2", "source": "ask", "target": "lookup"},
                {"id": "e3", "source": "lookup", "target": "done"},
            ],
        )
        flow2 = _sample_flow(
            "Human handoff",
            "Escalate a conversation to a human support agent.",
            "Use when the customer asks to speak with a human agent.",
            project.id,
            [
                {
                    "id": "notify",
                    "type": "message",
                    "position": {"x": 200, "y": 80},
                    "config": {"text": "Connecting you with a support agent now."},
                },
                {
                    "id": "handoff",
                    "type": "handoff",
                    "position": {"x": 200, "y": 240},
                    "config": {"queue_id": queue_id},
                },
            ],
            [{"id": "e1", "source": "notify", "target": "handoff"}],
        )
    else:
        flow1 = _sample_flow(
            "Track order",
            "Collect an order ID and look up its status.",
            "Use for order tracking and shipping status inquiries.",
            project.id,
            [
                {
                    "id": "welcome",
                    "type": "message",
                    "position": {"x": 200, "y": 60},
                    "config": {"text": welcome_text},
                },
                {
                    "id": "ask_order",
                    "type": "input",
                    "position": {"x": 200, "y": 210},
                    "config": {
                        "prompt": "Please share your order ID.",
                        "variable": "order_id",
                    },
                },
                {
                    "id": "lookup",
                    "type": "tool",
                    "position": {"x": 200, "y": 360},
                    "config": {
                        "tool_id": primary_tool.id,
                        "args": {"order_id": "{{order_id}}"},
                        "save_as": "order_result",
                    },
                },
                {
                    "id": "done",
                    "type": "end",
                    "position": {"x": 200, "y": 510},
                    "config": {"text": "Here are your order details. Reach out anytime!"},
                },
            ],
            [
                {"id": "e1", "source": "welcome", "target": "ask_order"},
                {"id": "e2", "source": "ask_order", "target": "lookup"},
                {"id": "e3", "source": "lookup", "target": "done"},
            ],
        )
        flow2 = _sample_flow(
            "Human handoff",
            "Transfer order exceptions to a human specialist.",
            "Use when a customer requests a human agent.",
            project.id,
            [
                {
                    "id": "notify",
                    "type": "message",
                    "position": {"x": 200, "y": 80},
                    "config": {"text": "Routing you to an orders specialist."},
                },
                {
                    "id": "handoff",
                    "type": "handoff",
                    "position": {"x": 200, "y": 240},
                    "config": {"queue_id": queue_id},
                },
            ],
            [{"id": "e1", "source": "notify", "target": "handoff"}],
        )

    db.add_all([flow1, flow2])
    db.flush()

    project.orchestrator = {
        "provider_id": chat_id,
        "description": project.description or agent_spec[1],
        "purpose": project.purpose or agent_spec[2],
        "instructions": "Route each customer request to the most relevant intent flow or agent.",
        "welcome": welcome_text,
        "flow_ids": [flow1.id, flow2.id],
        "agent_ids": [agent.id],
        "fallback_queue_id": queue_id,
    }


@router.post("/projects")
def create_project(body: ProjectIn, user=Depends(builders), db: DB = Depends(session)):
    if any(not public_origin(o) for o in body.origins):
        raise HTTPException(422, "Use exact http(s) origins")
    p = Project(**body.model_dump(exclude={"template"}))
    db.add(p)
    db.flush()
    _apply_project_template(db, p, body.template)
    db.commit()
    return project_view(p)


@router.put("/projects/{pid}")
def update_project(
    pid: str, body: ProjectIn, user=Depends(builders), db: DB = Depends(session)
):
    if any(not public_origin(o) for o in body.origins):
        raise HTTPException(422, "Use exact http(s) origins")
    p = require(db, Project, pid)
    for key, value in body.model_dump(exclude={"template"}).items():
        setattr(p, key, value)
    db.commit()
    return project_view(p)


def _ensure_nullable_agent_project(db: DB) -> None:
    bind = db.get_bind()
    if bind.dialect.name != "sqlite":
        return
    cols = db.execute(text("PRAGMA table_info(agents)")).fetchall()
    if not any(col[1] == "project_id" and col[3] == 1 for col in cols):
        return
    db.rollback()
    raw = engine.raw_connection()
    try:
        raw.execute("PRAGMA foreign_keys=OFF")
        raw.execute("BEGIN")
        raw.execute(
            "CREATE TABLE agents_new ("
            "project_id VARCHAR(36), "
            "name VARCHAR(120) NOT NULL, "
            "description TEXT NOT NULL, "
            "purpose TEXT NOT NULL, "
            "draft JSON NOT NULL, "
            "published_id VARCHAR(36), "
            "id VARCHAR(36) NOT NULL, "
            "created FLOAT NOT NULL, "
            "PRIMARY KEY (id), "
            "FOREIGN KEY(project_id) REFERENCES projects (id))"
        )
        raw.execute(
            "INSERT INTO agents_new (project_id, name, description, purpose, draft, published_id, id, created) "
            "SELECT project_id, name, description, purpose, draft, published_id, id, created FROM agents"
        )
        raw.execute("DROP TABLE agents")
        raw.execute("ALTER TABLE agents_new RENAME TO agents")
        raw.commit()
        raw.execute("PRAGMA foreign_keys=ON")
    finally:
        raw.close()


def _tool_ids_from_bot(draft: dict | None) -> set[str]:
    nodes = (draft or {}).get("nodes") or []
    return {
        n["data"]["tool_id"]
        for n in nodes
        if isinstance(n, dict)
        and isinstance(n.get("data"), dict)
        and isinstance(n["data"].get("tool_id"), str)
        and n["data"]["tool_id"]
    }


@router.delete("/projects/{pid}")
def delete_project(
    pid: str,
    keep_agents: bool = False,
    keep_tools: bool = False,
    user=Depends(builders),
    db: DB = Depends(session),
):
    p = require(db, Project, pid)
    if keep_agents:
        _ensure_nullable_agent_project(db)
        p = require(db, Project, pid)
    project_agents = list(db.scalars(select(Agent).where(Agent.project_id == pid)))
    project_bots = list(db.scalars(select(Bot).where(Bot.project_id == pid)))
    agent_ids = [a.id for a in project_agents]
    bot_ids = [b.id for b in project_bots]
    agent_version_ids = (
        list(
            db.scalars(
                select(AgentVersion.id).where(AgentVersion.agent_id.in_(agent_ids))
            )
        )
        if agent_ids
        else []
    )
    project_version_ids = list(
        db.scalars(select(ProjectVersion.id).where(ProjectVersion.project_id == pid))
    )

    candidate_tool_ids: set[str] = set()
    for a in project_agents:
        candidate_tool_ids.update((a.draft or {}).get("tool_ids") or [])
    for b in project_bots:
        candidate_tool_ids.update(_tool_ids_from_bot(b.draft))

    db.execute(
        update(Conversation)
        .where(Conversation.project_id == pid)
        .values(project_id=None, project_version_id=None)
    )
    if project_version_ids:
        db.execute(
            update(Conversation)
            .where(Conversation.project_version_id.in_(project_version_ids))
            .values(project_version_id=None)
        )

    if bot_ids:
        version_ids = list(
            db.scalars(select(Version.id).where(Version.bot_id.in_(bot_ids)))
        )
        db.execute(
            update(Conversation)
            .where(Conversation.bot_id.in_(bot_ids))
            .values(bot_id=None, version_id=None)
        )
        if version_ids:
            db.execute(
                update(Conversation)
                .where(Conversation.version_id.in_(version_ids))
                .values(version_id=None)
            )
        col_ids = list(
            db.scalars(select(Collection.id).where(Collection.bot_id.in_(bot_ids)))
        )
        if col_ids:
            doc_ids = list(
                db.scalars(
                    select(Document.id).where(Document.collection_id.in_(col_ids))
                )
            )
            if doc_ids:
                db.execute(delete(Chunk).where(Chunk.document_id.in_(doc_ids)))
            db.execute(delete(Document).where(Document.collection_id.in_(col_ids)))
            db.execute(delete(Collection).where(Collection.id.in_(col_ids)))
        db.execute(delete(Version).where(Version.bot_id.in_(bot_ids)))
        db.execute(delete(Bot).where(Bot.id.in_(bot_ids)))

    if keep_agents:
        if agent_ids:
            db.execute(
                update(Agent).where(Agent.id.in_(agent_ids)).values(project_id=None)
            )
    else:
        if agent_version_ids:
            db.execute(
                update(Conversation)
                .where(Conversation.active_agent_version_id.in_(agent_version_ids))
                .values(active_agent_version_id=None)
            )
            db.execute(
                delete(AgentVersion).where(AgentVersion.agent_id.in_(agent_ids))
            )
        if agent_ids:
            db.execute(delete(Agent).where(Agent.id.in_(agent_ids)))

    if not keep_tools and candidate_tool_ids:
        still_used: set[str] = set()
        for a in db.scalars(select(Agent)):
            still_used.update((a.draft or {}).get("tool_ids") or [])
        for b in db.scalars(select(Bot)):
            still_used.update(_tool_ids_from_bot(b.draft))
        unused_tool_ids = list(candidate_tool_ids - still_used)
        if unused_tool_ids:
            db.execute(
                delete(Invocation).where(Invocation.tool_id.in_(unused_tool_ids))
            )
            db.execute(delete(Tool).where(Tool.id.in_(unused_tool_ids)))

    db.execute(delete(ProjectVersion).where(ProjectVersion.project_id == pid))
    db.delete(p)
    db.commit()
    return {"deleted": pid}


@router.post("/projects/{pid}/validate")
def validate_project(pid: str, user=Depends(builders), db: DB = Depends(session)):
    snapshot, errors = project_snapshot(db, require(db, Project, pid))
    return {
        "errors": errors,
        "targets": {"flows": snapshot["flows"], "agents": snapshot["agents"]},
    }


def version_project(db, p, testing=False):
    snapshot, errors = project_snapshot(db, p)
    if errors:
        raise HTTPException(422, errors)
    v = ProjectVersion(
        project_id=p.id,
        number=sequence(db, ProjectVersion, "project_id", p.id, testing),
        snapshot=snapshot,
    )
    db.add(v)
    db.flush()
    return v


@router.post("/projects/{pid}/publish")
def publish_project(pid: str, user=Depends(builders), db: DB = Depends(session)):
    p = db.scalar(select(Project).where(Project.id == pid).with_for_update())
    if not p:
        raise HTTPException(404, "Project not found")
    v = version_project(db, p)
    p.published_id = v.id
    db.commit()
    return {"id": v.id, "number": v.number}


@router.post("/projects/{pid}/test")
def test_project(pid: str, user=Depends(builders), db: DB = Depends(session)):
    p = db.scalar(select(Project).where(Project.id == pid).with_for_update())
    if not p:
        raise HTTPException(404, "Project not found")
    v = version_project(db, p, True)
    return open_project_conversation(db, p, v, "test")


@router.get("/projects/{pid}/versions")
def project_versions(pid: str, user=Depends(builders), db: DB = Depends(session)):
    require(db, Project, pid)
    return [
        {"id": v.id, "number": v.number, "created": v.created}
        for v in db.scalars(
            select(ProjectVersion)
            .where(ProjectVersion.project_id == pid)
            .order_by(ProjectVersion.number.desc())
        )
    ]


@router.post("/widget/projects/{pid}/conversations")
def widget_project(pid: str, request: Request, db: DB = Depends(session)):
    p = require(db, Project, pid)
    origin = request.headers.get("origin", "")
    if origin not in p.origins:
        raise HTTPException(403, "Website origin is not allowed")
    if not p.published_id:
        raise HTTPException(409, "Project is not published")
    return open_project_conversation(
        db, p, require(db, ProjectVersion, p.published_id), origin
    )


@router.get("/agents")
def agents(
    project_id: str | None = None, user=Depends(builders), db: DB = Depends(session)
):
    statement = select(Agent).order_by(Agent.created)
    if project_id:
        statement = statement.where(Agent.project_id == project_id)
    return [agent_view(a) for a in db.scalars(statement)]


@router.post("/agents")
def create_agent(body: AgentIn, user=Depends(builders), db: DB = Depends(session)):
    require(db, Project, body.project_id)
    a = Agent(
        project_id=body.project_id,
        name=body.name,
        description=body.description,
        purpose=body.purpose,
        draft=body.definition.model_dump(),
    )
    db.add(a)
    db.commit()
    return agent_view(a)


@router.put("/agents/{aid}")
def update_agent(
    aid: str, body: AgentIn, user=Depends(builders), db: DB = Depends(session)
):
    a = require(db, Agent, aid)
    if a.project_id != body.project_id:
        raise HTTPException(422, "Agents cannot move between projects")
    a.name, a.description, a.purpose, a.draft = (
        body.name,
        body.description,
        body.purpose,
        body.definition.model_dump(),
    )
    db.commit()
    return {"agent": agent_view(a), "errors": validate_agent(db, a.project_id, a.draft)}


@router.post("/agents/{aid}/validate")
def validate_agent_route(aid: str, user=Depends(builders), db: DB = Depends(session)):
    a = require(db, Agent, aid)
    return {"errors": validate_agent(db, a.project_id, a.draft)}


@router.delete("/agents/{aid}")
def delete_agent(aid: str, user=Depends(builders), db: DB = Depends(session)):
    a = require(db, Agent, aid)
    version_ids = list(
        db.scalars(select(AgentVersion.id).where(AgentVersion.agent_id == aid))
    )
    if version_ids:
        db.execute(
            update(Conversation)
            .where(Conversation.active_agent_version_id.in_(version_ids))
            .values(active_agent_version_id=None)
        )
        db.execute(delete(AgentVersion).where(AgentVersion.agent_id == aid))
    for p in db.scalars(select(Project)):
        orch = p.orchestrator or {}
        agent_ids = orch.get("agent_ids") or []
        if aid in agent_ids:
            p.orchestrator = {
                **orch,
                "agent_ids": [x for x in agent_ids if x != aid],
            }
    db.delete(a)
    db.commit()
    return {"deleted": aid}


def version_agent(db, a, testing=False):
    errors = validate_agent(db, a.project_id, a.draft)
    if not testing and (not a.description.strip() or not a.purpose.strip()):
        errors.append("Agent description and purpose are required")
    if errors:
        raise HTTPException(422, errors)
    definition = {
        **a.draft,
        "name": a.name,
        "description": a.description,
        "purpose": a.purpose,
        "project_id": a.project_id,
    }
    v = AgentVersion(
        agent_id=a.id,
        number=sequence(db, AgentVersion, "agent_id", a.id, testing),
        definition=definition,
    )
    db.add(v)
    db.flush()
    return v


@router.post("/agents/{aid}/publish")
def publish_agent(aid: str, user=Depends(builders), db: DB = Depends(session)):
    a = db.scalar(select(Agent).where(Agent.id == aid).with_for_update())
    if not a:
        raise HTTPException(404, "Agent not found")
    v = version_agent(db, a)
    a.published_id = v.id
    db.commit()
    return {"id": v.id, "number": v.number}


@router.get("/agents/{aid}/versions")
def agent_versions(aid: str, user=Depends(builders), db: DB = Depends(session)):
    require(db, Agent, aid)
    return [
        {"id": v.id, "number": v.number, "created": v.created}
        for v in db.scalars(
            select(AgentVersion)
            .where(AgentVersion.agent_id == aid)
            .order_by(AgentVersion.number.desc())
        )
    ]


@router.post("/agents/{aid}/test")
def test_agent(aid: str, user=Depends(builders), db: DB = Depends(session)):
    a = require(db, Agent, aid)
    p = db.scalar(select(Project).where(Project.id == a.project_id).with_for_update())
    a = db.scalar(select(Agent).where(Agent.id == aid).with_for_update())
    av = version_agent(db, a, True)
    target = {
        "id": a.id,
        "name": a.name,
        "description": a.description,
        "purpose": a.purpose,
        "version_id": av.id,
    }
    snapshot = {
        "schema_version": 1,
        "name": p.name,
        "description": p.description,
        "purpose": p.purpose,
        "orchestrator": {
            "welcome": "Send a message to test this agent.",
            "fallback_queue_id": p.orchestrator.get("fallback_queue_id"),
        },
        "flows": [],
        "agents": [target],
        "test_agent_version_id": av.id,
    }
    pv = ProjectVersion(
        project_id=p.id,
        number=sequence(db, ProjectVersion, "project_id", p.id, True),
        snapshot=snapshot,
    )
    db.add(pv)
    db.flush()
    return open_project_conversation(db, p, pv, "test")
