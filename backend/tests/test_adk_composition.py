import json
from app import providers
from app.models import Bot, Version
from app.db import Session
from app.providers import Reply
from test_orchestration import configure, full_agent, intent, project, scripted, start_project
from test_platform import API, flow, history, message, publish


def test_agent_handoff_via_adk_sub_agents(admin, provider, drain, monkeypatch):
    p = project(admin, provider)
    billing = full_agent(admin, p, provider, instructions="BILLING SPECIALIST")
    r = admin.post(
        API + "/agents",
        json={
            "project_id": p["id"],
            "name": "Triage",
            "description": "Frontline triage agent",
            "purpose": "Route or handle customer questions",
            "definition": {
                "provider_id": provider["generation"]["id"],
                "instructions": "TRIAGE",
                "sub_agent_ids": [billing["id"]],
                "max_iterations": 4,
            },
        },
    )
    assert r.status_code == 200, r.text
    triage = r.json()
    assert admin.post(API + f"/agents/{triage['id']}/publish").status_code == 200
    configure(admin, p, agents=[triage])

    original = providers.adapter.generate

    def generate(db, prov, messages, tools, on_chunk, **kwargs):
        sys_prompt = messages[0]["content"]
        if sys_prompt.startswith("You route"):
            return original(db, prov, messages, tools, on_chunk, **kwargs)
        if "TRIAGE" in sys_prompt and messages[-1]["role"] != "tool":
            tool_names = [t["function"]["name"] for t in tools]
            assert "transfer_to_agent" in tool_names
            return Reply(
                calls=[
                    {
                        "id": "call_transfer",
                        "type": "function",
                        "function": {
                            "name": "transfer_to_agent",
                            "arguments": json.dumps({"agent_name": "Order_specialist_0"}),
                        },
                    }
                ]
            )
        if "BILLING SPECIALIST" in sys_prompt:
            return Reply(text="Billing specialist handled your refund.")
        return Reply(text="Triage done.")

    monkeypatch.setattr(providers.adapter, "generate", generate)
    scripted(monkeypatch, [{"target_type": "agent", "target_id": triage["id"]}])
    s = start_project(admin, p)
    drain()
    message(admin, s, "I need a refund")
    drain()
    h = history(admin, s)
    assert h["messages"][-1]["content"] == "Billing specialist handled your refund."


def test_agent_delegation_via_adk_agent_tool(admin, provider, drain, monkeypatch):
    p = project(admin, provider)
    specialist = full_agent(admin, p, provider, instructions="SHIPPING EXPERT")
    r = admin.post(
        API + "/agents",
        json={
            "project_id": p["id"],
            "name": "Coordinator",
            "description": "Coordinator agent",
            "purpose": "Coordinate specialists",
            "definition": {
                "provider_id": provider["generation"]["id"],
                "instructions": "COORDINATOR",
                "delegate_agent_ids": [specialist["id"]],
                "max_iterations": 4,
            },
        },
    )
    assert r.status_code == 200, r.text
    coord = r.json()
    assert admin.post(API + f"/agents/{coord['id']}/publish").status_code == 200
    configure(admin, p, agents=[coord])

    original = providers.adapter.generate

    def generate(db, prov, messages, tools, on_chunk, **kwargs):
        sys_prompt = messages[0]["content"]
        if sys_prompt.startswith("You route"):
            return original(db, prov, messages, tools, on_chunk, **kwargs)
        if "COORDINATOR" in sys_prompt:
            if messages[-1]["role"] != "tool":
                tool_names = [t["function"]["name"] for t in tools]
                assert "Order_specialist_0" in tool_names
                return Reply(
                    calls=[
                        {
                            "id": "call_delegate",
                            "type": "function",
                            "function": {
                                "name": "Order_specialist_0",
                                "arguments": json.dumps({"request": "Check shipping"}),
                            },
                        }
                    ]
                )
            return Reply(text="Synthesized: " + messages[-1]["content"])
        if "SHIPPING EXPERT" in sys_prompt:
            return Reply(text="Package arrives tomorrow")
        return Reply(text="Fallback")

    monkeypatch.setattr(providers.adapter, "generate", generate)
    scripted(monkeypatch, [{"target_type": "agent", "target_id": coord["id"]}])
    s = start_project(admin, p)
    drain()
    message(admin, s, "Where is my order?")
    drain()
    h = history(admin, s)
    assert "Package arrives tomorrow" in h["messages"][-1]["content"]


def test_flow_fanout_node_runs_parallel_agents_and_pins_versions(
    admin, provider, drain, monkeypatch
):
    p = project(admin, provider)
    a1 = full_agent(admin, p, provider, instructions="WORKER ONE")
    a2 = full_agent(admin, p, provider, instructions="WORKER TWO")
    b = intent(
        admin,
        p,
        definition=flow(
            [
                (
                    "welcome",
                    "fanout",
                    {
                        "agent_ids": [a1["id"], a2["id"]],
                        "mode": "parallel",
                        "variable": "fan_out",
                    },
                ),
                ("end", "end", {}),
            ],
            [("welcome", "next", "end"), ("welcome", "error", "end")],
        ),
    )
    configure(admin, p, flows=[b])

    with Session() as db:
        v = db.get(Version, db.get(Bot, b["id"]).published_id)
        pins = v.flow["nodes"][0]["config"]["agent_version_ids"]
        assert set(pins.keys()) == {a1["id"], a2["id"]}

    original = providers.adapter.generate

    def generate(db, prov, messages, tools, on_chunk, **kwargs):
        sys_prompt = messages[0]["content"]
        if sys_prompt.startswith("You route"):
            return original(db, prov, messages, tools, on_chunk, **kwargs)
        if "WORKER ONE" in sys_prompt:
            return Reply(text="One ready")
        if "WORKER TWO" in sys_prompt:
            return Reply(text="Two ready")
        return Reply(text="Other")

    monkeypatch.setattr(providers.adapter, "generate", generate)
    scripted(monkeypatch, [{"target_type": "flow", "target_id": b["id"]}])
    s = start_project(admin, p)
    drain()
    message(admin, s, "Check both")
    drain()
    h = history(admin, s)
    reply = h["messages"][-1]["content"]
    assert "One ready" in reply and "Two ready" in reply


def test_agentic_topology_test_endpoint_runs_adk_graph(
    admin, provider, drain, monkeypatch
):
    p = project(admin, provider)
    workflow = {
        "id": "wf-1",
        "project_id": p["id"],
        "name": "Support Mesh",
        "entry": "router",
        "nodes": [
            {
                "id": "router",
                "type": "router_agent",
                "name": "Router",
                "position": {"x": 0, "y": 0},
                "config": {
                    "provider_id": provider["generation"]["id"],
                    "instructions": "MESH ROUTER",
                },
            },
            {
                "id": "helper",
                "type": "agent",
                "name": "Helper",
                "position": {"x": 200, "y": 0},
                "config": {
                    "provider_id": provider["generation"]["id"],
                    "instructions": "MESH HELPER",
                },
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": "router",
                "target": "helper",
                "relation": "DELEGATE",
            }
        ],
    }

    def generate(db, prov, messages, tools, on_chunk, **kwargs):
        sys_prompt = messages[0]["content"]
        if "MESH ROUTER" in sys_prompt:
            if messages[-1]["role"] != "tool":
                helper_tool = next(
                    t["function"]["name"]
                    for t in tools
                    if t["function"]["name"].startswith("Helper_")
                )
                return Reply(
                    calls=[
                        {
                            "id": "call_mesh",
                            "type": "function",
                            "function": {
                                "name": helper_tool,
                                "arguments": json.dumps({"request": "Check status"}),
                            },
                        }
                    ]
                )
            return Reply(text="Mesh result: " + messages[-1]["content"])
        if "MESH HELPER" in sys_prompt:
            return Reply(text="Helper ready")
        return Reply(text="Other")

    monkeypatch.setattr(providers.adapter, "generate", generate)
    r = admin.post(API + f"/projects/{p['id']}/agentic/test", json={"workflow": workflow})
    assert r.status_code == 200, r.text
    s = r.json()
    s["headers"] = {"Authorization": "Bearer " + s["token"]}
    drain()
    message(admin, s, "Run mesh")
    drain()
    h = history(admin, s)
    assert "Helper ready" in h["messages"][-1]["content"]
