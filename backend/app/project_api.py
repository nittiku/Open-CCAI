"""Project orchestration and independently published full agents."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.orm import Session as DB
from .db import session
from .models import Project, ProjectVersion, Agent, AgentVersion, Bot, Conversation
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


@router.post("/projects")
def create_project(body: ProjectIn, user=Depends(builders), db: DB = Depends(session)):
    if any(not public_origin(o) for o in body.origins):
        raise HTTPException(422, "Use exact http(s) origins")
    p = Project(**body.model_dump())
    db.add(p)
    db.commit()
    return project_view(p)


@router.put("/projects/{pid}")
def update_project(
    pid: str, body: ProjectIn, user=Depends(builders), db: DB = Depends(session)
):
    if any(not public_origin(o) for o in body.origins):
        raise HTTPException(422, "Use exact http(s) origins")
    p = require(db, Project, pid)
    for key, value in body.model_dump().items():
        setattr(p, key, value)
    db.commit()
    return project_view(p)


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
