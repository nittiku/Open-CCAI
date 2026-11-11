# Open-CCAI

An Apache-2.0 contact-center automation platform you run yourself. Build website chatbots, connect your LLM API keys and business tools, answer from documents, and hand conversations to your own agents.

There is no project license server, platform traffic fee, required project-hosted service, or mandatory telemetry. Organizations pay their infrastructure and AI providers directly. Commercial LLM APIs are supported; running an open source model is optional.

**Status: initial implementation, intended for evaluation and development.** Run the checks and deployment smoke test on your target infrastructure before production use. No capacity or availability guarantee has been established.

## Included

- Project-level orchestrators that route requests to described intents (flows) or full agents, with clarification and human fallback.
- A separate Agent builder for independently versioned agents; inline flow AI steps are named Mini agents. Both reuse the shared tool library.

- React/TypeScript console with a React Flow visual builder, draft validation, immutable publication, test chat, and execution traces.
- Python/FastAPI API, Celery workers, RabbitMQ delivery, PostgreSQL state, pgvector retrieval, and local uploaded-file storage.
- OpenAI, Anthropic, Gemini, and OpenAI-compatible generation through an internal LiteLLM adapter; separate embedding connections.
- Text PDF, Markdown, and text ingestion with document references, deletion, and collection reindexing.
- Embeddable, dependency-free TypeScript chat widget with streaming, reconnects, deduplicated sends, and human handoff.
- Queues, availability, atomic manual claiming, agent replies, internal notes, conversation closure, and operational metrics.
- Setup-token protected administration, single-use invitations, four roles, encrypted API keys, credential rotation, and portable exports/imports.

Voice, telephony, WhatsApp, OCR, website crawling, enterprise SSO, shared multi-organization hosting, Kubernetes packaging, and editor-hosted arbitrary code are not included in this release.

## Run with Docker Compose

Requires Docker Engine/Desktop with Compose v2 and Python 3 for configuration.

```sh
python3 scripts/configure.py
docker compose up --build -d
```

Open **http://localhost:8080**. Read `SETUP_TOKEN` from your local `.env` file and use it to create the first administrator. The configuration generator creates unique secrets, refuses to overwrite `.env`, and sets mode 0600. No default administrator password exists.

The installation binds only to loopback. PostgreSQL and RabbitMQ are not published on host ports. The migration service completes before API and workers start.

### Try the full journey

1. Connect generation and embedding models in **Connections** using your own API keys.
2. Create a **Project** with its description and purpose.
3. Build intents in **Flow studio**. Each intent is a flow; add descriptions and purposes in intent settings, then publish. Use Mini agent steps for inline AI behavior or Agent steps to reuse published full agents.
4. Register business APIs in **Shared tools**. Create a full agent in **Agent builder** with instructions, model, enabled tools, and project knowledge, then publish it.
5. Upload documents in **Knowledge** and wait for indexing to finish. Mini agents can use their flow's collections; full agents can use collections within their project.
6. Configure the project orchestrator's description, purpose, model, enabled intents/agents, and human fallback. Test routing and inspect the execution traces, then publish the project.
7. Allow the website origin on the project and copy its widget snippet. The orchestrator routes each new request; active flows retain control until they finish or hand off.
8. In **Agent inbox**, set yourself available, claim a waiting conversation, reply, add an internal note, and close it.

See [projects and orchestration](docs/orchestration.md) for routing behavior, version pinning, migration compatibility, and APIs. Existing direct `data-bot` widgets remain supported.

### Embed

```html
<script src="https://contact.example.com/widget/open-ccai.js"
  data-api="https://contact.example.com"
  data-project="YOUR_PROJECT_ID"
  data-title="How can we help?" defer></script>
```

Serve the installation over HTTPS before embedding on an HTTPS website. Allow the website origin on the project. The widget stores its conversation capability in the website's session storage, never in a URL, and excludes dashboard cookies. Website CSP rules must allow the script and HTTPS/WebSocket connections to your installation.

## Local demo — one command

Requires Node 24 and Python 3.12+. After `npm ci`, run:

```sh
npm run dev
```

The launcher prepares the Python environment if needed, runs demo migrations, seeds the playground once, and starts the API, background worker, and console together. Open the **URL printed in the terminal**; available ports are selected automatically when another app already uses 5173 or 8000.

- **Email:** `demo@openccai.local`
- **Password:** `OpenCCAI-Demo123!`

The playground includes a project orchestrator, a Returns intent with a Mini agent, an Orders specialist, a shared fictional order-lookup tool, and a knowledge document. In **Projects → Test**, try **return an order**, **track order DEMO-1001**, or **talk to a person**. The demo administrator is available to claim handoffs in Agent inbox.

Local mock models and the sample lookup require no API keys or external requests. Real model connections you add use their normal adapters and provider billing. Mock replies are marked as demo data.

Your playground edits persist in **`data/demo/`**, with separate private keys and a dedicated SQLite database. Restarting does not overwrite your changes. Demo startup does not read the production database URL or alter `.env`. Docker/normal API startup creates no dummy account. Ctrl+C stops the three demo processes together.

## Development with real services

Use the regular application database and keys when working outside the demo:

```sh
python3 -m venv .venv
.venv/bin/pip install -c backend/requirements.lock -e 'backend[test]'
npm ci
python3 scripts/configure.py
.venv/bin/python scripts/dev.py migrate
```

Run in three terminals:

```sh
.venv/bin/python scripts/dev.py api
.venv/bin/python scripts/dev.py worker
npm run dev:frontend
```

Vite proxies API and WebSockets to port 8000 by default. `CCAI_API_URL` can select a different local API address. SQLite is a development/test convenience; deployments use PostgreSQL and RabbitMQ through Compose.

To test the separately built widget, run `npm run build` and serve `widget/dist` from your test website. The Compose console serves it automatically at `/widget/`.

## Verification

```sh
npm run build
npm test
.venv/bin/pytest backend/tests -q
```

To include PostgreSQL concurrency/vector tests, use a **disposable, dedicated** database (tests drop all application tables):

```sh
TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost/ccai_test \
  .venv/bin/pytest backend/tests -q
```

Set `TEST_PG_BIN` to the directory containing matching PostgreSQL `pg_dump`, `pg_restore`, `createdb`, and `dropdb` tools to include the database/files/credential restore round-trip. Set `TEST_BROKER_URL` as well to exercise actual RabbitMQ delivery. CI runs SQLite and PostgreSQL tests, broker delivery, both frontend builds, Compose image builds, the deployment smoke test, and a backup/restore smoke round-trip. Run `python3 scripts/smoke.py` only against a **fresh disposable** Compose installation: it initializes an administrator and creates a sample conversation.

Live-provider tests require `RUN_LIVE_PROVIDER_TESTS=1`, the provider's API-key environment variable, and `OPENAI_TEST_MODEL`, `ANTHROPIC_TEST_MODEL`, or `GEMINI_TEST_MODEL`. They incur provider usage and are skipped by default. Provider adapter mocks verify routing and streaming without paid calls.

See [architecture](docs/architecture.md), [operations](docs/operations.md), [API and portability](docs/api.md), [verification notes](docs/verification.md), and [contributing](CONTRIBUTING.md).
