# API and portability

The API reference is served at `/api/v1/docs`; the machine-readable OpenAPI schema is at `/api/v1/openapi.json`. Both are available through the console and direct local API. The reference uses only locally served assets. All business endpoints are versioned under `/api/v1`.

Dashboard authentication uses an HTTP-only SameSite Strict cookie scoped to `/api`, secure by default. Mutation requests with browser origins must match `APP_ORIGINS`. Scripted clients can use the same login/cookie flow. Web chat uses `Authorization: Bearer <conversation-token>` on widget REST requests and sends `{ "token": "..." }` as the first WebSocket message. The widget uses `POST /widget/conversations/{id}/history` for resume so browsers reliably send their Origin header even on same-origin requests; GET history remains available to API clients. Browser widget origins must match the bot's current allowlist and the token's bound origin.

## Main endpoints

| Area | Routes |
|---|---|
| Setup and authentication | `GET /auth/status`, `POST /auth/setup`, `/auth/login`, `/auth/logout`, `/auth/accept`, `GET /auth/me` |
| Team | `GET /users`, `POST /invitations`, `/users/availability` |
| Secrets and providers | `GET/POST /credentials`, `PUT /credentials/{id}`, `GET/POST /providers` |
| Bots | `GET/POST /bots`, `PUT /bots/{id}`, `PUT /bots/{id}/draft`, `POST /bots/{id}/validate`, `/publish`, `/test`, `GET /bots/{id}/versions` |
| Knowledge | `GET/POST /collections`, `GET/POST /collections/{id}/documents`, `POST /collections/{id}/reindex`, `DELETE /documents/{id}` |
| Extensions | `GET/POST /tools`, `GET/POST /queues` |
| Public website | `POST /widget/bots/{id}/conversations`, `GET /widget/conversations/{id}`, `POST /widget/conversations/{id}/messages`, `/handoff` |
| Agent workspace | `GET /conversations`, `GET /conversations/{id}`, `POST /conversations/{id}/claim`, `/messages`, `/notes`, `/close` |
| Operations | `GET /monitoring`, `/conversations/{id}/traces`, `/conversations/{id}/invocations` |
| Export/import | `GET /bots/{id}/export`, `POST /bots/import`, `GET /conversations/{id}/export` |
| Realtime | WebSocket `/events/{conversation_id}` |

Paths in this table are relative to `/api/v1`. Message sends require `{ "content": "...", "client_id": "stable-unique-id" }`. Retry the same logical send with the same ID. Invitation tokens are returned once to the administrator and never sent by email by the platform.

## Workflow schema 1

```json
{
  "schema_version": 1,
  "entry": "greeting",
  "nodes": [
    {"id": "greeting", "type": "message", "position": {"x": 40, "y": 80}, "config": {"text": "Hello"}},
    {"id": "finish", "type": "end", "position": {"x": 320, "y": 80}, "config": {}}
  ],
  "edges": [{"id": "edge1", "source": "greeting", "target": "finish", "label": "next"}]
}
```

Node types: `message`, `input`, `condition`, `variable`, `tool`, `knowledge`, `ai` (Mini agent), `agent` (published full agent), `handoff`, `end`. `condition` uses `true`/`false` branches; AI/tool/knowledge nodes require `next`/`error`; handoff/end are terminal. Text/arguments can interpolate `${variable}`. Conditions compare a variable to the configured JSON value; no expressions or arbitrary code are evaluated. Custom code runs behind registered HTTP tools.

## Export/import

Bot export includes schema version, workflow, provider descriptors, tool schema descriptors, queue descriptors, and knowledge-collection metadata/document names. It excludes API keys, credential IDs, tool bearer secrets, transcripts, and source document contents. Export files can still contain organization-authored workflow instructions and business configuration; treat them accordingly.

Import requires explicit mappings from old resource references to local connections/tools/queues. It creates an unpublished bot with an empty website allowlist. Collections are recreated empty; documents must be reuploaded and ingested. Provider names alone never silently bind credentials.

```json
{
  "bundle": {"schema_version": 1, "name": "Example", "flow": {}, "providers": [], "tools": [], "queues": [], "collections": []},
  "provider_bindings": {"old-provider-ref": "local-provider-id"},
  "tool_bindings": {"old-tool-ref": "local-tool-id"},
  "queue_bindings": {"old-queue-ref": "local-queue-id"}
}
```

The `flow` above is illustrative; supply a valid exported workflow. Conversation exports are separate and include customer/agent/bot messages and internal notes. They contain customer data and are restricted to operational roles.

## Projects and agents

See [orchestration APIs and lifecycle](orchestration.md) for project/agent CRUD, publication, testing, routing catalogs, and project widget sessions. `/bots` remains the compatibility wire name for intents/flows. Flow imports may also provide `project_id` and `agent_bindings`; referenced full agents must be published in the destination project.
