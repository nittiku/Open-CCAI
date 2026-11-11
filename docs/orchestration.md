# Projects, orchestration, and agents

A **project** owns an **orchestrator**, a set of **intents / flows**, and a set of reusable **full agents**. An intent is a flow. The orchestrator chooses which enabled intent or agent should handle an incoming request, using their descriptions and purposes and the conversation context.

A **Mini agent** is an inline AI step in a flow. A **full agent** is authored separately in Agent builder, published independently, and reusable as an orchestrator target or an Agent step in a flow. Human support agents continue to work in Agent inbox; they are distinct from these automated agents.

## Build a project

1. Create a project in **Projects**, or select one from the sidebar. Each project has its own orchestrator configuration.
2. Connect your generation model in **Connections**. In **Shared tools**, register any HTTP tools you want to make available across agents and flows.
3. Create intents in **Flow studio**. In intent settings, give each a description and purpose explaining when it should run. Publish each intent after validating its graph.
4. Create full agents in **Agent builder**. Configure their description, purpose, instructions, generation model, enabled shared tools, knowledge collections, execution limit, and optional output schema. Publish agents you want to reuse.
5. In **Projects**, describe the orchestrator and its purpose, select its model, configure an optional human fallback queue, and enable its intended flows and agents. Only published targets from that project can be enabled for routing.
6. Test the orchestrator. Execution traces show which target it selected. Publish the project when ready, allow the website origin, and use the project's widget snippet.

Tools are registered once per installation. Full agents, Mini agents, and HTTP tool steps reference the same tool IDs and the same schema validation, authentication, destination restrictions, invocation records, and retry semantics. An agent can call only the tools explicitly enabled for it.

Knowledge remains scoped: Mini agents use their flow's collections; full agents may select collections belonging to intents in their own project. Foreign project knowledge and agents are rejected at publication.

## Conversation behavior

The project sends its configured welcome message and waits for a customer request. The orchestrator makes one bounded model call to choose an enabled flow or agent, ask for clarification, or queue a human handoff. Model output is validated against the published target catalog; invented, foreign, malformed, or unavailable targets are not executed. Provider/routing failures queue a human handoff and create an error trace.

When routing into a flow, the initiating request is available as `${request}` and `${question}`. The routing message is consumed once; subsequent input nodes collect new customer messages. An active flow retains control until completion or human handoff. A flow's end node returns to the project orchestrator; it does not close the entire project conversation. Direct legacy flow sessions retain their previous behavior, where an end node closes the session.

A full agent executes a bounded turn, can retrieve project knowledge and call its enabled tools, and returns control to the orchestrator after replying. Conversation context persists between turns. Buffered requests are processed in arrival order; later messages are excluded from the model context of an earlier routed request. Agent failures queue the configured human fallback. Human handoff increments ownership revision and stops pending automated output.

Agent draft tests target the selected draft directly, without needing a fully configured orchestrator. Project tests use the current orchestrator draft and the published versions of its enabled targets.

## Publication and compatibility

Publishing a project snapshots its descriptions, routing instructions, enabled target metadata, and published flow/agent version IDs. Existing sessions stay on their starting project release. Publishing a new agent or flow does not silently change an existing project release: publish the project again to adopt it for new sessions.

An Agent step inside a flow pins the selected full-agent version when the flow is published. Mini agents retain the `ai` workflow node type for compatibility; reusable full-agent steps use `agent` with `agent_id`. The server resolves and pins `agent_version_id`, rather than trusting caller-supplied version IDs.

The migration creates a project around each existing bot/flow and preserves its published versions, website origins, and conversation history. Existing `data-bot` widgets and `/api/v1/bots` endpoints still start direct flow sessions. New project widgets use:

```html
<script src="https://contact.example.com/widget/open-ccai.js"
  data-api="https://contact.example.com"
  data-project="YOUR_PROJECT_ID" defer></script>
```

Run migrations before starting the updated backend: `.venv/bin/python scripts/dev.py migrate` for local development, or the Compose migration service for deployment. Configure the new orchestrator before publishing a migrated project. Existing direct flows continue to run without requiring an orchestrator model.

## API additions

- `GET/POST /api/v1/projects`, `PUT /api/v1/projects/{id}`.
- `POST /api/v1/projects/{id}/validate`, `/publish`, `/test`; `GET /api/v1/projects/{id}/versions`.
- `GET/POST /api/v1/agents`, `PUT /api/v1/agents/{id}`.
- `POST /api/v1/agents/{id}/validate`, `/publish`, `/test`; `GET /api/v1/agents/{id}/versions`.
- `POST /api/v1/widget/projects/{id}/conversations` for an origin-bound project session.
- Existing flow APIs accept `project_id`, `description`, and `purpose`. Project reassignment is rejected to preserve knowledge and agent isolation.
- Flow bundles include optional full-agent descriptors. Import supplies `project_id` and explicit `agent_bindings`, alongside existing provider/tool/queue bindings. Import never binds an arbitrary foreign agent or silently reuses a pinned version from another installation.

Project and agent management use builder/administrator permissions. Shared tool registration remains administrator-controlled. Widget capabilities are bound to their project, conversation, and origin and continue to work as the conversation routes between targets.
