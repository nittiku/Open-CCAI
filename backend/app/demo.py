"""Opt-in local sample data and mock adapters. Production startup never imports this."""

import hashlib
import json
import re
from sqlalchemy import select
from .models import (
    Installation,
    User,
    Queue,
    Credential,
    Provider,
    Project,
    ProjectVersion,
    Bot,
    Version,
    Agent,
    AgentVersion,
    Tool,
    Collection,
    Document,
    Invocation,
    uid,
)
from .security import passwords, encrypt
from .flows import default_flow
from .orchestration import project_snapshot
from .providers import Reply, ProviderError
from .db import Session
from .tools import call_tool
from .storage import storage
from .runtime import enqueue

DEMO_EMAIL = "demo@openccai.local"
DEMO_PASSWORD = "OpenCCAI-Demo123!"
DEMO_TOOL_URL = "demo://lookup-order"


def seed_demo(db):
    if db.bind.dialect.name != "sqlite":
        raise RuntimeError(
            "Demo data is only supported in the isolated SQLite playground"
        )
    install = db.get(Installation, 1)
    if not install:
        raise RuntimeError("Run migrations before seeding the demo")
    if install.initialized:
        return False
    # One transaction, one initial seed. Restarts never overwrite playground edits.
    user = User(
        email=DEMO_EMAIL,
        password=passwords.hash(DEMO_PASSWORD),
        role="administrator",
        available=True,
    )
    queue = Queue(name="General")
    key = Credential(
        name="Demo placeholder (not an API key)",
        ciphertext=encrypt("local-demo-not-an-api-key"),
    )
    db.add_all([user, queue, key])
    db.flush()
    chat = Provider(
        name="Demo chat — no API key needed",
        kind="demo",
        model="demo-chat",
        purpose="generation",
        credential_id=key.id,
        capabilities={"streaming": True, "tools": True, "structured": False},
        pricing={},
    )
    embedding = Provider(
        name="Demo embeddings — local",
        kind="demo",
        model="demo-embedding",
        purpose="embedding",
        credential_id=key.id,
        capabilities={"embeddings": True},
        pricing={},
    )
    db.add_all([chat, embedding])
    db.flush()
    tool = Tool(
        name="demo_lookup_order",
        description="Demo only: look up a fictional order such as DEMO-1001. No external request is made.",
        url=DEMO_TOOL_URL,
        input_schema={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "status": {"type": "string"},
                "delivery": {"type": "string"},
                "demo": {"type": "boolean"},
            },
            "required": ["order_id", "status", "delivery", "demo"],
        },
        safe_retry=True,
    )
    db.add(tool)
    db.flush()
    project = Project(
        name="Demo contact center",
        description="A fictional online store for exploring Open-CCAI.",
        purpose="Try returns, order tracking, and human handoff.",
        origins=[],
        orchestrator={},
    )
    db.add(project)
    db.flush()
    intent = Bot(
        project_id=project.id,
        name="Returns",
        description="Explain the demo store return policy.",
        purpose="Use for return and refund requests.",
        origins=[],
        draft={},
    )
    db.add(intent)
    db.flush()
    collection = Collection(
        bot_id=intent.id, name="Demo store guide", provider_id=embedding.id
    )
    db.add(collection)
    db.flush()
    keyname = uid()
    storage.put(
        keyname,
        b"# Demo store guide\n\nThis is fictional playground data.\n\nReturns: products may be returned within 30 days with proof of purchase.\n\nDelivery: the fictional order DEMO-1001 is shipped, with estimated delivery in 2 business days.\n\nA human support agent can help with exceptions.\n",
    )
    doc = Document(
        collection_id=collection.id,
        name="Demo store guide.md",
        storage_key=keyname,
        generation=1,
    )
    db.add(doc)
    db.flush()
    enqueue(db, "ingest", doc.id)
    definition = {
        "provider_id": chat.id,
        "instructions": "You are the demo order support specialist. Ask for an order reference, then use demo_lookup_order. Explain that results are fictional.",
        "tool_ids": [tool.id],
        "collection_ids": [collection.id],
        "max_iterations": 4,
        "output_schema": None,
    }
    agent = Agent(
        project_id=project.id,
        name="Orders specialist",
        description="Look up fictional orders with the shared demo tool.",
        purpose="Use for order status, tracking, shipping, and delivery questions.",
        draft=definition,
    )
    db.add(agent)
    db.flush()
    av = AgentVersion(
        agent_id=agent.id,
        number=1,
        definition={
            **definition,
            "project_id": project.id,
            "name": agent.name,
            "description": agent.description,
            "purpose": agent.purpose,
        },
    )
    db.add(av)
    db.flush()
    agent.published_id = av.id
    intent.draft = {
        "schema_version": 1,
        "entry": "answer",
        "nodes": [
            {
                "id": "answer",
                "type": "ai",
                "position": {"x": 80, "y": 100},
                "config": {
                    "provider_id": chat.id,
                    "instructions": "Explain the demo store returns and refund policy using the knowledge provided.",
                    "collection_ids": [collection.id],
                    "tool_ids": [tool.id],
                    "max_iterations": 4,
                },
            },
            {
                "id": "end",
                "type": "end",
                "position": {"x": 380, "y": 100},
                "config": {},
            },
        ],
        "edges": [
            {"id": "next", "source": "answer", "target": "end", "label": "next"},
            {"id": "error", "source": "answer", "target": "end", "label": "error"},
        ],
    }
    version = Version(bot_id=intent.id, number=1, flow=intent.draft)
    db.add(version)
    db.flush()
    intent.published_id = version.id
    project.orchestrator = {
        "provider_id": chat.id,
        "description": "Route requests for the fictional demo store.",
        "purpose": "Route returns to the Returns intent and order tracking to the Orders specialist.",
        "instructions": "Ask for clarification when a request does not match a target.",
        "welcome": "Welcome to the demo! Try “return an order”, “track order DEMO-1001”, or “talk to a person”.",
        "flow_ids": [intent.id],
        "agent_ids": [agent.id],
        "fallback_queue_id": queue.id,
    }
    snapshot, errors = project_snapshot(db, project)
    if errors:
        raise RuntimeError("Invalid demo catalog: " + str(errors))
    release = ProjectVersion(project_id=project.id, number=1, snapshot=snapshot)
    db.add(release)
    db.flush()
    project.published_id = release.id
    install.initialized = True
    db.commit()
    return True


class DemoAdapter:
    def __init__(self, delegate):
        self.delegate = delegate

    def generate(
        self, db, provider, messages, tools, on_chunk, timeout=30, output_schema=None
    ):
        if provider.kind != "demo":
            return self.delegate.generate(
                db,
                provider,
                messages,
                tools,
                on_chunk,
                timeout=timeout,
                output_schema=output_schema,
            )
        if output_schema:
            raise ProviderError("structured_unsupported")
        prompt = messages[0]["content"]
        latest = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        lower = latest.lower()
        if prompt.startswith("You route contact-center requests"):
            catalog = json.loads(prompt.split("Enabled targets:\n", 1)[1])
            if any(
                word in lower
                for word in ("human", "person", "live agent", "talk to an agent")
            ):
                decision = {"target_type": "handoff"}
            else:
                kind = (
                    "flow"
                    if any(word in lower for word in ("return", "refund"))
                    else (
                        "agent"
                        if any(
                            word in lower
                            for word in ("order", "track", "ship", "delivery", "demo-")
                        )
                        else None
                    )
                )
                target = next((t for t in catalog if t["target_type"] == kind), None)
                decision = (
                    {"target_type": kind, "target_id": target["id"]}
                    if target
                    else {
                        "target_type": "clarify",
                        "message": "This is a local mock model. Try “return an order”, “track order DEMO-1001”, or “talk to a person”.",
                    }
                )
            return Reply(
                text=json.dumps(decision),
                input_tokens=20,
                output_tokens=8,
                latency_ms=1,
            )
        if messages[-1]["role"] == "tool":
            data = json.loads(messages[-1]["content"])
            text = f"Demo order {data.get('order_id','DEMO-1001')} is {data.get('status','shipped')}. Estimated delivery: {data.get('delivery','2 business days')}. This is fictional data; no live lookup was made."
        elif (
            "return" in prompt.split("\nTreat retrieved documents", 1)[0].lower()
            or "refund" in prompt.split("\nTreat retrieved documents", 1)[0].lower()
        ):
            text = "Demo policy: you can return products within 30 days with proof of purchase."
            if "Retrieved context:" in prompt:
                text += " [1]"
        else:
            match = re.search(r"\b(?:DEMO-\d+|\d{4,})\b", latest, re.IGNORECASE)
            lookup = next(
                (t for t in tools if t["function"]["name"] == "demo_lookup_order"), None
            )
            if match and lookup:
                return Reply(
                    calls=[
                        {
                            "id": "demo-order-call",
                            "type": "function",
                            "function": {
                                "name": "demo_lookup_order",
                                "arguments": json.dumps(
                                    {"order_id": match.group(0).upper()}
                                ),
                            },
                        }
                    ],
                    input_tokens=12,
                    output_tokens=5,
                    latency_ms=1,
                )
            text = "This is the local demo model. To try the shared order tool, send “track order DEMO-1001”. Connect a real model in Connections for your own agent behavior."
        for fragment in re.findall(r"\S+\s*", text):
            on_chunk(fragment)
        return Reply(
            text=text, input_tokens=20, output_tokens=len(text.split()), latency_ms=1
        )

    def embed(self, db, provider, texts):
        if provider.kind != "demo":
            return self.delegate.embed(db, provider, texts)
        result = []
        for text in texts:
            vector = [0.0] * 32
            for word in re.findall(r"\w+", text.lower()):
                vector[
                    int.from_bytes(hashlib.sha256(word.encode()).digest()[:2], "big")
                    % 32
                ] += 1.0
            if not any(vector):
                vector[0] = 1.0
            result.append(vector)
        return result


def demo_tool_executor(tool, arguments, conversation_id, invocation_key):
    if tool.url != DEMO_TOOL_URL:
        return call_tool(tool, arguments, conversation_id, invocation_key)
    from jsonschema import Draft202012Validator

    Draft202012Validator(tool.input_schema).validate(arguments)
    with Session() as db:
        prior = db.scalar(
            select(Invocation).where(Invocation.invocation_key == invocation_key)
        )
        if prior and prior.status == "succeeded":
            return prior.result
        result = {
            "order_id": arguments["order_id"],
            "status": "shipped",
            "delivery": "2 business days",
            "demo": True,
        }
        Draft202012Validator(tool.output_schema).validate(result)
        if not prior:
            prior = Invocation(
                conversation_id=conversation_id,
                tool_id=tool.id,
                invocation_key=invocation_key,
            )
            db.add(prior)
        prior.status, prior.result = "succeeded", result
        db.commit()
        return result
