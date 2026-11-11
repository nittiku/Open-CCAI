import asyncio
import hmac
import json
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Request,
    Response,
    UploadFile,
    File,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DB
from jsonschema import Draft202012Validator
from .config import settings, validate_settings
from .db import session, Session
from .models import (
    Installation,
    User,
    Invitation,
    Credential,
    Provider,
    Queue,
    Bot,
    Version,
    Conversation,
    Message,
    Event,
    Job,
    Trace,
    Tool,
    Invocation,
    Collection,
    Document,
    Chunk,
    AuthLimit,
    Project,
    ProjectVersion,
    Agent,
    uid,
)
from .schemas import (
    Setup,
    Login,
    Invite,
    Accept,
    CredentialIn,
    ProviderIn,
    Named,
    BotIn,
    DraftIn,
    MessageIn,
    ToolIn,
    CollectionIn,
    ReindexIn,
    ImportIn,
)
from .security import (
    current_user,
    admins,
    builders,
    operators,
    readers,
    passwords,
    token,
    decode,
    encrypt,
    digest,
    public_origin,
    outbound_url,
)
from .flows import default_flow, validate_flow
from .orchestration import pin_flow_agents
from .runtime import enqueue, emit, add_message
from .storage import storage
from .channels import web_chat


@asynccontextmanager
async def lifespan(app):
    validate_settings()
    yield


app = FastAPI(
    title="Open-CCAI",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def origin_security(request: Request, call_next):
    origin = request.headers.get("origin")
    widget = request.url.path.startswith("/api/v1/widget/")
    if request.method == "OPTIONS" and widget:
        # Widget capabilities are bearer-authenticated; never expose dashboard cookies.
        response = Response(status_code=204)
        response.headers.update(
            {
                "Access-Control-Allow-Origin": origin or "",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                "Access-Control-Allow-Headers": "Authorization,Content-Type",
                "Vary": "Origin",
            }
        )
        return response
    if (
        origin
        and not widget
        and request.method not in ("GET", "HEAD", "OPTIONS")
        and origin not in settings.origins
    ):
        return JSONResponse({"detail": "Untrusted origin"}, status_code=403)
    response = await call_next(request)
    if widget and origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        if "access-control-allow-credentials" in response.headers:
            del response.headers["access-control-allow-credentials"]
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


from fastapi.exceptions import RequestValidationError


@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc):
    # Validation payloads must not echo submitted passwords or API keys.
    return JSONResponse(
        {
            "detail": [
                {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
                for e in exc.errors()
            ]
        },
        status_code=422,
    )


@app.exception_handler(IntegrityError)
async def conflict_handler(request, exc):
    return JSONResponse(
        {"detail": "Conflicting record; reload and retry"}, status_code=409
    )


# Authentication responses deliberately contain no password hashes or credential material.
def user_view(u):
    return {"id": u.id, "email": u.email, "role": u.role, "available": u.available}


def get(db, cls, rid):
    row = db.get(cls, rid)
    if not row:
        raise HTTPException(404, "Record not found")
    return row


def set_cookie(response, user):
    response.set_cookie(
        "ccai_session",
        token(user.id, "user"),
        httponly=True,
        secure=settings.secure_cookie,
        samesite="strict",
        max_age=28800,
        path="/api",
    )


def login_limit(db, key):
    # Persistent fixed-window limits also apply across API replicas.
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    key = digest(key) + ":" + str(int(time.time() // 60))
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    db.execute(
        insert(AuthLimit)
        .values(id=key, count=0)
        .on_conflict_do_nothing(index_elements=["id"])
    )
    row = db.scalar(select(AuthLimit).where(AuthLimit.id == key).with_for_update())
    row.count += 1
    db.commit()
    if row.count > 10:
        raise HTTPException(429, "Too many attempts; try again in a minute")


@app.get("/api/v1/health")
def health(db: DB = Depends(session)):
    db.execute(select(Installation.id).limit(1))
    return {"status": "ok"}


@app.get("/api/v1/auth/status")
def auth_status(db: DB = Depends(session)):
    row = db.get(Installation, 1)
    return {"initialized": bool(row and row.initialized)}


@app.post("/api/v1/auth/setup")
def setup(body: Setup, response: Response, request: Request, db: DB = Depends(session)):
    login_limit(db, "setup:" + (request.client.host if request.client else "unknown"))
    if not hmac.compare_digest(body.setup_token, settings.setup_token):
        raise HTTPException(403, "Invalid setup token")
    installation = db.scalar(
        select(Installation).where(Installation.id == 1).with_for_update()
    )
    if not installation:
        raise HTTPException(503, "Run database migrations first")
    if installation.initialized:
        raise HTTPException(409, "Installation already initialized")
    user = User(
        email=body.email, password=passwords.hash(body.password), role="administrator"
    )
    db.add(user)
    installation.initialized = True
    db.add(Queue(name="General"))
    db.commit()
    set_cookie(response, user)
    return user_view(user)


@app.post("/api/v1/auth/login")
def login(body: Login, response: Response, db: DB = Depends(session)):
    login_limit(db, "login:" + body.email)
    user = db.scalar(select(User).where(User.email == body.email))
    if not user or not passwords.verify(body.password, user.password):
        raise HTTPException(401, "Invalid email or password")
    set_cookie(response, user)
    return user_view(user)


@app.post("/api/v1/auth/logout")
def logout(response: Response):
    response.delete_cookie(
        "ccai_session",
        path="/api",
        secure=settings.secure_cookie,
        httponly=True,
        samesite="strict",
    )
    return {"ok": True}


@app.get("/api/v1/auth/me")
def me(user=Depends(current_user)):
    return user_view(user)


@app.get("/api/v1/users")
def users(user=Depends(admins), db: DB = Depends(session)):
    return [user_view(u) for u in db.scalars(select(User).order_by(User.created))]


@app.post("/api/v1/invitations")
def invite(body: Invite, user=Depends(admins), db: DB = Depends(session)):
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(422, "Email required")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "User already exists")
    raw = secrets.token_urlsafe(32)
    db.add(
        Invitation(
            email=email,
            role=body.role,
            token_hash=digest(raw),
            expires=time.time() + 86400,
        )
    )
    db.commit()
    # Display once for the administrator to deliver; the platform sends no email.
    return {"token": raw, "expires_in": 86400, "email": email}


@app.post("/api/v1/auth/accept")
def accept(body: Accept, response: Response, db: DB = Depends(session)):
    login_limit(db, "accept:" + body.email)
    row = db.scalar(
        select(Invitation)
        .where(Invitation.token_hash == digest(body.invitation_token))
        .with_for_update()
    )
    if not row or row.used or row.expires < time.time() or row.email != body.email:
        raise HTTPException(400, "Invalid invitation")
    user = User(email=row.email, role=row.role, password=passwords.hash(body.password))
    db.add(user)
    row.used = True
    db.commit()
    set_cookie(response, user)
    return user_view(user)


@app.post("/api/v1/users/availability")
def availability(body: dict, user=Depends(operators), db: DB = Depends(session)):
    if not isinstance(body.get("available"), bool):
        raise HTTPException(422, "available must be boolean")
    user.available = body["available"]
    db.add(user)
    db.commit()
    return user_view(user)


@app.get("/api/v1/credentials")
def credentials(user=Depends(admins), db: DB = Depends(session)):
    return [{"id": x.id, "name": x.name} for x in db.scalars(select(Credential))]


@app.post("/api/v1/credentials")
def create_credential(
    body: CredentialIn, user=Depends(admins), db: DB = Depends(session)
):
    row = Credential(name=body.name, ciphertext=encrypt(body.secret))
    db.add(row)
    db.commit()
    return {"id": row.id, "name": row.name}


@app.put("/api/v1/credentials/{rid}")
def rotate_credential(
    rid: str, body: CredentialIn, user=Depends(admins), db: DB = Depends(session)
):
    row = get(db, Credential, rid)
    row.name = body.name
    row.ciphertext = encrypt(body.secret)
    db.commit()
    return {"id": row.id, "name": row.name}


def provider_view(p):
    return {
        k: getattr(p, k)
        for k in (
            "id",
            "name",
            "kind",
            "model",
            "purpose",
            "base_url",
            "capabilities",
            "pricing",
            "credential_id",
        )
    }


@app.get("/api/v1/providers")
def provider_list(user=Depends(builders), db: DB = Depends(session)):
    return [
        provider_view(p)
        for p in db.scalars(select(Provider).order_by(Provider.created))
    ]


@app.post("/api/v1/providers")
def create_provider(body: ProviderIn, user=Depends(admins), db: DB = Depends(session)):
    get(db, Credential, body.credential_id)
    if body.base_url:
        try:
            outbound_url(body.base_url, settings.provider_hosts)
        except (ValueError, OSError):
            raise HTTPException(
                422, "Provider endpoint is not an allowed public HTTPS destination"
            )
    if body.kind == "compatible" and not body.base_url:
        raise HTTPException(422, "Compatible providers require base_url")
    if body.purpose == "embedding" and body.kind == "anthropic":
        raise HTTPException(422, "Choose an embedding-capable provider")
    if any(
        k not in ("input_per_million", "output_per_million") or v < 0
        for k, v in body.pricing.items()
    ):
        raise HTTPException(422, "Invalid pricing")
    caps = (
        {
            "streaming": True,
            "tools": body.kind != "compatible",
            "structured": body.kind == "openai",
        }
        if body.purpose == "generation"
        else {"embeddings": True}
    )
    caps.update(body.capabilities)
    row = Provider(**{**body.model_dump(), "capabilities": caps})
    db.add(row)
    db.commit()
    return provider_view(row)


@app.get("/api/v1/queues")
def queues(user=Depends(readers), db: DB = Depends(session)):
    return [{"id": q.id, "name": q.name} for q in db.scalars(select(Queue))]


@app.post("/api/v1/queues")
def create_queue(body: Named, user=Depends(admins), db: DB = Depends(session)):
    q = Queue(name=body.name)
    db.add(q)
    db.commit()
    return {"id": q.id, "name": q.name}


def bot_view(b):
    return {
        k: getattr(b, k)
        for k in (
            "id",
            "name",
            "draft",
            "published_id",
            "origins",
            "project_id",
            "description",
            "purpose",
        )
    }


@app.get("/api/v1/bots")
def bots(user=Depends(builders), db: DB = Depends(session)):
    return [bot_view(b) for b in db.scalars(select(Bot).order_by(Bot.created))]


@app.post("/api/v1/bots")
def create_bot(body: BotIn, user=Depends(builders), db: DB = Depends(session)):
    if any(not public_origin(o) for o in body.origins):
        raise HTTPException(422, "Use exact http(s) origins without paths or wildcards")
    if body.project_id:
        project = get(db, Project, body.project_id)
    else:
        project = Project(
            name=body.name,
            description=body.description,
            purpose=body.purpose,
            origins=body.origins,
            orchestrator={},
        )
        db.add(project)
        db.flush()
    b = Bot(
        project_id=project.id,
        description=body.description,
        purpose=body.purpose,
        name=body.name,
        origins=body.origins,
        draft=default_flow(db.scalar(select(Queue.id).where(Queue.name == "General"))),
    )
    db.add(b)
    db.commit()
    return bot_view(b)


@app.put("/api/v1/bots/{bid}")
def update_bot(
    bid: str, body: BotIn, user=Depends(builders), db: DB = Depends(session)
):
    if any(not public_origin(o) for o in body.origins):
        raise HTTPException(422, "Invalid origin")
    b = get(db, Bot, bid)
    if body.project_id and body.project_id != b.project_id:
        raise HTTPException(422, "Flows cannot move between projects")
    b.name = body.name
    b.description, b.purpose = body.description, body.purpose
    b.origins = body.origins
    db.commit()
    return bot_view(b)


@app.put("/api/v1/bots/{bid}/draft")
def save_draft(
    bid: str, body: DraftIn, user=Depends(builders), db: DB = Depends(session)
):
    if len(json.dumps(body.flow)) > 500_000:
        raise HTTPException(413, "Flow too large")
    b = get(db, Bot, bid)
    errors = validate_flow(body.flow, db, bid)
    b.draft = body.flow
    db.commit()
    return {"bot": bot_view(b), "errors": errors}


@app.post("/api/v1/bots/{bid}/validate")
def validate_bot(bid: str, user=Depends(builders), db: DB = Depends(session)):
    b = get(db, Bot, bid)
    return {"errors": validate_flow(b.draft, db, bid)}


@app.post("/api/v1/bots/{bid}/publish")
def publish(bid: str, user=Depends(builders), db: DB = Depends(session)):
    b = db.scalar(select(Bot).where(Bot.id == bid).with_for_update())
    if not b:
        raise HTTPException(404, "Bot not found")
    errors = validate_flow(b.draft, db, bid)
    if errors:
        raise HTTPException(422, errors)
    number = (
        db.scalar(select(func.max(Version.number)).where(Version.bot_id == bid)) or 0
    ) + 1
    version = Version(bot_id=bid, number=number, flow=pin_flow_agents(db, b.draft))
    db.add(version)
    db.flush()
    b.published_id = version.id
    db.commit()
    return {"id": version.id, "number": version.number}


@app.get("/api/v1/bots/{bid}/versions")
def versions(bid: str, user=Depends(builders), db: DB = Depends(session)):
    get(db, Bot, bid)
    return [
        {"id": v.id, "number": v.number, "created": v.created}
        for v in db.scalars(
            select(Version).where(Version.bot_id == bid).order_by(Version.number.desc())
        )
    ]


def tool_view(t):
    return {
        k: getattr(t, k)
        for k in (
            "id",
            "name",
            "description",
            "url",
            "method",
            "input_schema",
            "output_schema",
            "credential_id",
            "timeout",
            "safe_retry",
        )
    }


@app.get("/api/v1/tools")
def tools(user=Depends(builders), db: DB = Depends(session)):
    return [tool_view(t) for t in db.scalars(select(Tool))]


@app.post("/api/v1/tools")
def create_tool(body: ToolIn, user=Depends(admins), db: DB = Depends(session)):
    try:
        outbound_url(body.url, settings.tool_hosts)
        Draft202012Validator.check_schema(body.input_schema)
        Draft202012Validator.check_schema(body.output_schema)
    except Exception:
        raise HTTPException(422, "Invalid schemas or disallowed HTTPS destination")
    if body.input_schema.get("type") != "object":
        raise HTTPException(422, "Tool inputs must use an object schema")
    if body.credential_id:
        get(db, Credential, body.credential_id)
    t = Tool(**body.model_dump())
    db.add(t)
    db.commit()
    return tool_view(t)


@app.get("/api/v1/collections")
def collections(user=Depends(builders), db: DB = Depends(session)):
    return [
        {
            "id": c.id,
            "name": c.name,
            "bot_id": c.bot_id,
            "provider_id": c.provider_id,
            "generation": c.generation,
        }
        for c in db.scalars(select(Collection))
    ]


@app.post("/api/v1/collections")
def create_collection(
    body: CollectionIn, user=Depends(builders), db: DB = Depends(session)
):
    get(db, Bot, body.bot_id)
    if get(db, Provider, body.provider_id).purpose != "embedding":
        raise HTTPException(422, "Embedding provider required")
    c = Collection(**body.model_dump())
    db.add(c)
    db.commit()
    return {"id": c.id, "name": c.name}


@app.get("/api/v1/collections/{cid}/documents")
def documents(cid: str, user=Depends(builders), db: DB = Depends(session)):
    get(db, Collection, cid)
    return [
        {
            "id": d.id,
            "name": d.name,
            "status": d.status,
            "error": d.error,
            "created": d.created,
        }
        for d in db.scalars(select(Document).where(Document.collection_id == cid))
    ]


@app.post("/api/v1/collections/{cid}/documents")
async def upload(
    cid: str,
    file: UploadFile = File(...),
    user=Depends(builders),
    db: DB = Depends(session),
):
    c = get(db, Collection, cid)
    name = (file.filename or "").replace("\\", "/").split("/")[-1][:250]
    if not name.lower().endswith((".pdf", ".md", ".txt")):
        raise HTTPException(422, "Upload a PDF, Markdown, or text file")
    content = await file.read(10_000_001)
    if len(content) > 10_000_000:
        raise HTTPException(413, "Maximum upload is 10 MB")
    key = uid()
    storage.put(key, content)
    d = Document(collection_id=cid, name=name, storage_key=key, generation=c.generation)
    db.add(d)
    db.flush()
    enqueue(db, "ingest", d.id)
    try:
        db.commit()
    except Exception:
        storage.delete(key)
        raise
    return {"id": d.id, "status": d.status}


@app.delete("/api/v1/documents/{did}")
def delete_document(did: str, user=Depends(builders), db: DB = Depends(session)):
    d = get(db, Document, did)
    key = d.storage_key
    db.execute(delete(Chunk).where(Chunk.document_id == did))
    db.delete(d)
    db.commit()
    storage.delete(key)
    return {"ok": True}


@app.post("/api/v1/collections/{cid}/reindex")
def reindex(
    cid: str, body: ReindexIn, user=Depends(builders), db: DB = Depends(session)
):
    c = db.scalar(select(Collection).where(Collection.id == cid).with_for_update())
    if not c:
        raise HTTPException(404, "Collection not found")
    if body.provider_id:
        if get(db, Provider, body.provider_id).purpose != "embedding":
            raise HTTPException(422, "Embedding provider required")
        c.provider_id = body.provider_id
    c.generation += 1
    for d in db.scalars(select(Document).where(Document.collection_id == cid)):
        d.status = "pending"
        d.generation = c.generation
        enqueue(db, "ingest", d.id)
    db.commit()
    return {"generation": c.generation}


def conversation_view(c):
    return {
        k: getattr(c, k)
        for k in (
            "id",
            "bot_id",
            "version_id",
            "project_id",
            "project_version_id",
            "execution_mode",
            "active_agent_version_id",
            "status",
            "waiting",
            "queue_id",
            "agent_id",
            "created",
            "queued_at",
            "closed_at",
        )
    }


def transcript(db, c, internal=False):
    roles_filter = (
        ["customer", "bot", "agent", "note"]
        if internal
        else ["customer", "bot", "agent"]
    )
    result = conversation_view(c)
    result["messages"] = [
        web_chat.outbound(m)
        for m in db.scalars(
            select(Message)
            .where(Message.conversation_id == c.id, Message.role.in_(roles_filter))
            .order_by(Message.created, Message.id)
        )
    ]
    return result


def start_conversation(db, bot, version_id):
    version = get(db, Version, version_id)
    c = Conversation(
        bot_id=bot.id,
        project_id=bot.project_id,
        version_id=version_id,
        node_id=version.flow["entry"],
    )
    db.add(c)
    db.flush()
    enqueue(db, "conversation", c.id)
    emit(db, c.id, "state", {"status": "bot"})
    db.commit()
    return c


@app.post("/api/v1/bots/{bid}/test")
def test_chat(bid: str, user=Depends(builders), db: DB = Depends(session)):
    b = db.scalar(select(Bot).where(Bot.id == bid).with_for_update())
    if not b:
        raise HTTPException(404, "Bot not found")
    errors = validate_flow(b.draft, db, bid)
    if errors:
        raise HTTPException(422, errors)
    # Draft tests receive an immutable snapshot without changing the published pointer.
    number = (
        db.scalar(
            select(func.min(Version.number)).where(
                Version.bot_id == bid, Version.number < 0
            )
        )
        or 0
    ) - 1
    v = Version(bot_id=bid, number=number, flow=pin_flow_agents(db, b.draft))
    db.add(v)
    db.flush()
    c = start_conversation(db, b, v.id)
    return {
        "conversation_id": c.id,
        "token": token(c.id, "widget", 86400, bot_id=bid, origin="test"),
    }


@app.post("/api/v1/widget/bots/{bid}/conversations")
def widget_start(bid: str, request: Request, db: DB = Depends(session)):
    b = get(db, Bot, bid)
    origin = request.headers.get("origin", "")
    if origin not in b.origins:
        raise HTTPException(403, "Website origin is not allowed")
    if not b.published_id:
        raise HTTPException(409, "Bot is not published")
    c = start_conversation(db, b, b.published_id)
    return {
        "conversation_id": c.id,
        "token": token(c.id, "widget", 86400, bot_id=bid, origin=origin),
    }


def widget_owner(db, c):
    return (
        get(db, Project, c.project_id)
        if c.project_version_id
        else get(db, Bot, c.bot_id)
    )


def authorize_widget(db, c, claims, origin, allow_no_test_origin=False):
    if claims["sub"] != c.id:
        raise HTTPException(403, "Conversation mismatch")
    key, expected = (
        ("project_id", c.project_id) if c.project_version_id else ("bot_id", c.bot_id)
    )
    if claims.get(key) != expected:
        raise HTTPException(403, "Conversation scope mismatch")
    if claims.get("origin") == "test":
        if origin not in settings.origins and not (allow_no_test_origin and not origin):
            raise HTTPException(403, "Invalid test origin")
    elif origin != claims.get("origin") or origin not in widget_owner(db, c).origins:
        raise HTTPException(403, "Website origin is not allowed")


def widget_conversation(cid, request, db):
    raw = request.headers.get("authorization", "").removeprefix("Bearer ")
    claims = decode(raw, "widget")
    c = get(db, Conversation, cid)
    authorize_widget(
        db, c, claims, request.headers.get("origin", ""), allow_no_test_origin=True
    )
    return c


@app.post("/api/v1/widget/conversations/{cid}/history")
@app.get("/api/v1/widget/conversations/{cid}")
def widget_history(cid: str, request: Request, db: DB = Depends(session)):
    return transcript(db, widget_conversation(cid, request, db))


@app.post("/api/v1/widget/conversations/{cid}/messages")
def widget_message(
    cid: str, body: MessageIn, request: Request, db: DB = Depends(session)
):
    widget_conversation(cid, request, db)
    c = db.scalar(select(Conversation).where(Conversation.id == cid).with_for_update())
    old = db.scalar(
        select(Message).where(
            Message.conversation_id == cid,
            Message.role == "customer",
            Message.client_id == body.client_id,
        )
    )
    if old:
        return {"id": old.id, "duplicate": True}
    if c.status not in ("bot", "queued", "agent"):
        raise HTTPException(409, "Conversation is not accepting messages")
    inbound = web_chat.inbound(body.model_dump())
    m = add_message(db, cid, "customer", inbound.content, inbound.client_id)
    if c.status == "bot":
        enqueue(db, "conversation", cid)
    db.commit()
    return {"id": m.id}


@app.post("/api/v1/widget/conversations/{cid}/handoff")
def widget_handoff(cid: str, request: Request, db: DB = Depends(session)):
    widget_conversation(cid, request, db)
    c = db.scalar(select(Conversation).where(Conversation.id == cid).with_for_update())
    if c.status == "bot":
        c.status = "queued"
        if c.project_version_id:
            release = get(db, ProjectVersion, c.project_version_id)
            c.queue_id = release.snapshot["orchestrator"].get("fallback_queue_id")
        else:
            c.queue_id = db.scalar(select(Queue.id).where(Queue.name == "General"))
        c.queued_at = time.time()
        c.revision += 1
        emit(db, cid, "state", {"status": "queued"})
        db.commit()
    return conversation_view(c)


@app.get("/api/v1/conversations")
def conversation_list(user=Depends(operators), db: DB = Depends(session)):
    return [
        conversation_view(c)
        for c in db.scalars(
            select(Conversation).order_by(Conversation.created.desc()).limit(200)
        )
    ]


@app.get("/api/v1/conversations/{cid}")
def conversation_detail(cid: str, user=Depends(readers), db: DB = Depends(session)):
    return transcript(db, get(db, Conversation, cid), True)


@app.get("/api/v1/conversations/{cid}/traces")
def traces(cid: str, user=Depends(readers), db: DB = Depends(session)):
    get(db, Conversation, cid)
    return [
        {
            "id": t.id,
            "node_id": t.node_id,
            "status": t.status,
            "detail": t.detail,
            "created": t.created,
        }
        for t in db.scalars(
            select(Trace).where(Trace.conversation_id == cid).order_by(Trace.created)
        )
    ]


@app.get("/api/v1/conversations/{cid}/invocations")
def invocations(cid: str, user=Depends(operators), db: DB = Depends(session)):
    get(db, Conversation, cid)
    return [
        {
            "id": i.id,
            "tool_id": i.tool_id,
            "status": i.status,
            "invocation_key": i.invocation_key,
        }
        for i in db.scalars(select(Invocation).where(Invocation.conversation_id == cid))
    ]


@app.post("/api/v1/conversations/{cid}/claim")
def claim(cid: str, user=Depends(operators), db: DB = Depends(session)):
    c = db.scalar(select(Conversation).where(Conversation.id == cid).with_for_update())
    if not c:
        raise HTTPException(404, "Conversation not found")
    if not user.available:
        raise HTTPException(409, "Set yourself available first")
    if c.status != "queued" or c.agent_id:
        raise HTTPException(409, "Conversation is no longer available")
    c.status = "agent"
    c.agent_id = user.id
    c.revision += 1
    emit(db, cid, "state", {"status": "agent"})
    db.commit()
    return conversation_view(c)


@app.post("/api/v1/conversations/{cid}/messages")
def agent_reply(
    cid: str, body: MessageIn, user=Depends(operators), db: DB = Depends(session)
):
    c = db.scalar(select(Conversation).where(Conversation.id == cid).with_for_update())
    if not c:
        raise HTTPException(404, "Conversation not found")
    if c.status != "agent" or c.agent_id != user.id:
        raise HTTPException(409, "Claim this conversation before replying")
    old = db.scalar(
        select(Message).where(
            Message.conversation_id == cid,
            Message.role == "agent",
            Message.client_id == body.client_id,
        )
    )
    if old:
        return {"id": old.id, "duplicate": True}
    m = add_message(db, cid, "agent", body.content, body.client_id)
    db.commit()
    return {"id": m.id}


@app.post("/api/v1/conversations/{cid}/notes")
def note(cid: str, body: MessageIn, user=Depends(operators), db: DB = Depends(session)):
    get(db, Conversation, cid)
    old = db.scalar(
        select(Message).where(
            Message.conversation_id == cid,
            Message.role == "note",
            Message.client_id == body.client_id,
        )
    )
    if old:
        return {"id": old.id, "duplicate": True}
    m = add_message(db, cid, "note", body.content, body.client_id)
    db.commit()
    return {"id": m.id}


@app.post("/api/v1/conversations/{cid}/close")
def close(cid: str, user=Depends(operators), db: DB = Depends(session)):
    c = db.scalar(select(Conversation).where(Conversation.id == cid).with_for_update())
    if not c:
        raise HTTPException(404, "Conversation not found")
    if c.agent_id != user.id and user.role not in ("administrator", "supervisor"):
        raise HTTPException(403, "Only assigned agent or supervisor can close")
    c.status = "closed"
    c.closed_at = time.time()
    c.revision += 1
    emit(db, cid, "state", {"status": "closed"})
    db.commit()
    return conversation_view(c)


@app.get("/api/v1/monitoring")
def monitoring(user=Depends(operators), db: DB = Depends(session)):
    counts = dict(
        db.execute(
            select(Conversation.status, func.count()).group_by(Conversation.status)
        ).all()
    )
    waits = [
        time.time() - q
        for q in db.scalars(
            select(Conversation.queued_at).where(
                Conversation.status == "queued", Conversation.queued_at.is_not(None)
            )
        )
    ]
    traces = db.scalars(select(Trace).order_by(Trace.created.desc()).limit(1000)).all()
    usage = [u for t in traces for u in t.detail.get("usage", [])]
    return {
        "counts": counts,
        "active": sum(counts.get(s, 0) for s in ("bot", "queued", "agent")),
        "queue_depth": counts.get("queued", 0),
        "longest_wait_seconds": max(waits, default=0),
        "handoffs": db.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.queued_at.is_not(None))
        ),
        "execution_errors": sum(t.status == "error" for t in traces),
        "input_tokens": sum(u["input_tokens"] for u in usage),
        "output_tokens": sum(u["output_tokens"] for u in usage),
        "average_model_latency_ms": (
            sum(u["latency_ms"] for u in usage) / len(usage) if usage else None
        ),
        "estimated_cost": (
            sum(
                u["estimated_cost"]
                for u in usage
                if u.get("estimated_cost") is not None
            )
            if any(u.get("estimated_cost") is not None for u in usage)
            else None
        ),
        "usage_scope": "Latest 1,000 workflow traces",
        "closed_is_resolution": False,
    }


@app.websocket("/api/v1/events/{cid}")
async def events(ws: WebSocket, cid: str):
    origin = ws.headers.get("origin", "")
    await ws.accept()
    try:
        auth = await asyncio.wait_for(ws.receive_json(), timeout=5)
        expires = time.time() + 28800
        with Session() as db:
            c = get(db, Conversation, cid)
            if auth.get("token"):
                claims = decode(auth["token"], "widget")
                expires = claims["exp"]
                authorize_widget(db, c, claims, origin)
                internal = False
            else:
                claims = decode(ws.cookies.get("ccai_session", ""), "user")
                expires = claims["exp"]
                if origin not in settings.origins or not db.get(User, claims["sub"]):
                    raise HTTPException(403)
                internal = True
            # Capture boundary before snapshot so a concurrent event cannot be lost.
            cursor = time.time()
            seen = {
                e.id
                for e in db.scalars(
                    select(Event).where(
                        Event.conversation_id == cid, Event.created >= cursor - 180
                    )
                )
            }
            current = transcript(db, c, internal)
            await ws.send_json({"kind": "snapshot", "payload": current})
            signature = (c.status, c.agent_id, len(current["messages"]))
        while time.time() < expires:
            with Session() as db:
                c = get(db, Conversation, cid)
                if (
                    not internal
                    and claims.get("origin") != "test"
                    and origin not in widget_owner(db, c).origins
                ):
                    break
                boundary = time.time()
                rows = db.scalars(
                    select(Event)
                    .where(
                        Event.conversation_id == cid,
                        Event.created >= boundary - 180,
                        Event.created < boundary,
                    )
                    .order_by(Event.created, Event.id)
                ).all()
                recent_ids = {e.id for e in rows}
                for event in rows:
                    if event.id in seen:
                        continue
                    if (
                        not internal
                        and event.kind == "message"
                        and event.payload.get("role") == "note"
                    ):
                        continue
                    # Ownership changes invalidate any queued bot chunks.
                    if event.kind == "chunk" and (
                        c.status != "bot" or event.payload.get("step") != c.steps
                    ):
                        continue
                    await ws.send_json(
                        {"id": event.id, "kind": event.kind, "payload": event.payload}
                    )
                seen = recent_ids
                current = transcript(db, c, internal)
                next_signature = (c.status, c.agent_id, len(current["messages"]))
                if signature != next_signature:
                    await ws.send_json({"kind": "snapshot", "payload": current})
                    signature = next_signature
                cursor = boundary
            await ws.send_json({"kind": "heartbeat", "payload": {}})
            await asyncio.sleep(0.5)
    except (
        HTTPException,
        WebSocketDisconnect,
        asyncio.TimeoutError,
        ValueError,
        KeyError,
    ):
        pass
    finally:
        try:
            await ws.close(code=1000)
        except (RuntimeError, WebSocketDisconnect):
            pass


@app.get("/api/v1/bots/{bid}/export")
def export_bot(bid: str, user=Depends(builders), db: DB = Depends(session)):
    bot = get(db, Bot, bid)
    cols = db.scalars(select(Collection).where(Collection.bot_id == bid)).all()
    provider_ids = {c.provider_id for c in cols}
    tool_ids = set()
    queue_ids = set()
    agent_ids = set()
    for n in bot.draft.get("nodes", []):
        cfg = n.get("config", {})
        if n.get("type") == "agent" and cfg.get("agent_id"):
            agent_ids.add(cfg["agent_id"])
        if cfg.get("provider_id"):
            provider_ids.add(cfg["provider_id"])
        if cfg.get("tool_id"):
            tool_ids.add(cfg["tool_id"])
        tool_ids.update(cfg.get("tool_ids", []))
        if cfg.get("queue_id"):
            queue_ids.add(cfg["queue_id"])
    return {
        "schema_version": 1,
        "name": bot.name,
        "description": bot.description,
        "purpose": bot.purpose,
        "flow": bot.draft,
        "agents": [
            {"ref": a.id, "name": a.name}
            for aid in sorted(agent_ids)
            if (a := db.get(Agent, aid))
        ],
        "providers": [
            {
                "ref": p.id,
                "name": p.name,
                "kind": p.kind,
                "model": p.model,
                "purpose": p.purpose,
            }
            for pid in sorted(provider_ids)
            if (p := db.get(Provider, pid))
        ],
        "tools": [
            {
                "ref": t.id,
                "name": t.name,
                "input_schema": t.input_schema,
                "output_schema": t.output_schema,
            }
            for tid in sorted(tool_ids)
            if (t := db.get(Tool, tid))
        ],
        "queues": [
            {"ref": q.id, "name": q.name}
            for qid in sorted(queue_ids)
            if (q := db.get(Queue, qid))
        ],
        "collections": [
            {
                "ref": c.id,
                "name": c.name,
                "provider_ref": c.provider_id,
                "documents": [
                    d.name
                    for d in db.scalars(
                        select(Document).where(Document.collection_id == c.id)
                    )
                ],
            }
            for c in cols
        ],
    }


@app.post("/api/v1/bots/import")
def import_bot(body: ImportIn, user=Depends(builders), db: DB = Depends(session)):
    bundle = body.bundle
    if bundle.get("schema_version") != 1:
        raise HTTPException(422, "Unsupported bundle version")
    try:
        flow = json.loads(json.dumps(bundle["flow"]))
        if len(json.dumps(bundle)) > 500_000:
            raise ValueError()
        for p in bundle.get("providers", []):
            get(db, Provider, body.provider_bindings[p["ref"]])
        for t in bundle.get("tools", []):
            get(db, Tool, body.tool_bindings[t["ref"]])
        for q in bundle.get("queues", []):
            get(db, Queue, body.queue_bindings[q["ref"]])
        if body.project_id:
            project = get(db, Project, body.project_id)
        else:
            project = Project(
                name=str(bundle.get("name", "Imported flow"))[:120],
                description="",
                purpose="",
                origins=[],
                orchestrator={},
            )
            db.add(project)
            db.flush()
        for descriptor in bundle.get("agents", []):
            target = get(db, Agent, body.agent_bindings[descriptor["ref"]])
            if target.project_id != project.id or not target.published_id:
                raise ValueError()
        bot = Bot(
            name=str(bundle.get("name", "Imported bot"))[:120],
            project_id=project.id,
            description=str(bundle.get("description", ""))[:5000],
            purpose=str(bundle.get("purpose", ""))[:5000],
            origins=[],
            draft={},
        )
        db.add(bot)
        db.flush()
        colmap = {}
        for c in bundle.get("collections", []):
            provider_id = body.provider_bindings[c["provider_ref"]]
            if get(db, Provider, provider_id).purpose != "embedding":
                raise ValueError()
            col = Collection(bot_id=bot.id, name=c["name"], provider_id=provider_id)
            db.add(col)
            db.flush()
            colmap[c["ref"]] = col.id
        for n in flow["nodes"]:
            cfg = n.get("config", {})
            if n.get("type") == "agent":
                cfg["agent_id"] = body.agent_bindings[cfg["agent_id"]]
                cfg.pop("agent_version_id", None)
            if cfg.get("provider_id"):
                cfg["provider_id"] = body.provider_bindings[cfg["provider_id"]]
            if cfg.get("tool_id"):
                cfg["tool_id"] = body.tool_bindings[cfg["tool_id"]]
            if cfg.get("tool_ids"):
                cfg["tool_ids"] = [body.tool_bindings[x] for x in cfg["tool_ids"]]
            if cfg.get("queue_id"):
                cfg["queue_id"] = body.queue_bindings[cfg["queue_id"]]
            if cfg.get("collection_ids"):
                cfg["collection_ids"] = [colmap[x] for x in cfg["collection_ids"]]
        errors = validate_flow(flow, db, bot.id)
        if errors:
            raise HTTPException(422, errors)
        bot.draft = flow
        db.commit()
        return {"bot": bot_view(bot), "requires_document_upload": bool(colmap)}
    except (KeyError, TypeError, ValueError):
        db.rollback()
        raise HTTPException(422, "Malformed bundle or missing resource bindings")


@app.get("/api/v1/conversations/{cid}/export")
def export_conversation(cid: str, user=Depends(operators), db: DB = Depends(session)):
    return {
        "schema_version": 1,
        "conversation": transcript(db, get(db, Conversation, cid), True),
    }


# Keep API documentation accessible through the same reverse-proxy prefix.
@app.get("/api/v1/openapi.json", include_in_schema=False)
def versioned_openapi():
    return app.openapi()


@app.get("/api/v1/docs", include_in_schema=False)
def versioned_docs():
    from fastapi.responses import HTMLResponse

    return HTMLResponse(
        """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Open-CCAI API reference</title><style>body{font:14px system-ui;background:#f6f8f3;color:#244a36;max-width:1100px;margin:40px auto;padding:20px}h1{letter-spacing:-1px}p{color:#7b9070;line-height:1.8}a{color:#24634f}details{border:1px solid #dfe8d6;border-radius:7px;background:white;margin:8px 0}summary{cursor:pointer;padding:15px;display:flex;gap:15px;align-items:center;font-size:12px}summary b{width:55px;color:#487c52}summary span{margin-left:auto;color:#8c9b7d}pre{padding:20px;margin:0;background:#edf3e7;overflow:auto;font-size:11px;line-height:1.7}</style><script src="/api/v1/docs.js" defer></script></head><body><h1>Open-CCAI API reference</h1><p>Version 1 · Self-hosted contact-center automation.<br>Dashboard requests use an authenticated session cookie. Widget requests use an origin-bound conversation bearer token.<br><a href="/api/v1/openapi.json">Download the OpenAPI schema</a> for use with your preferred API client.</p><main id="operations"></main></body></html>"""
    )


@app.get("/api/v1/docs.js", include_in_schema=False)
def docs_script():
    from pathlib import Path
    from fastapi.responses import FileResponse

    return FileResponse(
        Path(__file__).parent / "static" / "docs.js",
        media_type="application/javascript",
    )


from .project_api import router as project_router

app.include_router(project_router)
