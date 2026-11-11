# Verification record

The automated suite uses deterministic model/embedding adapters and mock HTTP transports. It covers authentication and encrypted credential storage; roles and invitation restrictions; workflow validation and pinned versions; bot/customer/agent messaging; document ingestion, isolation, reindex exclusion, and deletion; source references; provider routing and normalized failures; output-schema validation; iteration-limit accounting; expired job leases; idempotent messages/actions; uncertain external actions; late bot-output suppression after handoff; widget origins/capabilities; and WebSocket history/note isolation.

PostgreSQL concurrency and RabbitMQ delivery tests are conditional on dedicated test-service environment variables. Paid provider tests are opt-in. A passing mock test is not evidence that a particular organization/model combination has been tested live.

CI additionally builds the Compose images and runs `scripts/smoke.py` against the complete fresh deployment. The smoke requires no paid model key and exercises a deterministic message/input/handoff workflow through the actual API, database, scheduler, broker, and worker.

## Initial local verification

- React console and standalone widget: TypeScript checks and production builds passed.
- Backend: SQLite integration and provider/tool contract tests passed (44 passed; six environment-specific skips).
- PostgreSQL 18.0 with pgvector 0.8.7: **46 passed, 4 skipped**, including concurrent claims and a real dump/restore round-trip of transcripts, vectors, files, and encrypted credentials. Skips were RabbitMQ delivery and the three opt-in live providers.
- Widget: two URL regression tests passed. Browser checks confirmed saving preserves canvas nodes, test chat hands off, the inbox accepts agent replies, and the standalone widget resumes history and receives human replies.
- A second-origin browser test was not performed: automatic approval review rejected changing the disposable bot’s allowlist. The existing origin was retained; API tests cover cross-origin allow/deny behavior.
- Alembic: initial migration and metadata-drift check passed against fresh local SQLite and PostgreSQL databases.
- Python dependency resolution: `pip check` passed.
- Docker/Compose: unavailable on the development host; image startup, RabbitMQ delivery, and the Docker orchestration in the backup/restore scripts must be verified in CI or a Docker-capable environment. The underlying PostgreSQL dump/restore and uploaded-file round-trip were verified locally.
- Live provider calls: not run; no organization API keys were used.
- Capacity: no production limit is claimed. `scripts/load.py` is supplied for an explicit baseline on the target installation.

Consult current CI and rerun checks after changing code; this document records the initial implementation, not a guarantee of a later checkout or deployment.

## Projects and agents update

- PostgreSQL suite: **62 passed, 4 skipped**, including project-to-flow/agent routing, clarification, invalid-target and provider-error fallback, immutable agent/version references, shared full/Mini agent tools, buffered request ordering, project knowledge isolation, agent draft tests, widget capability scope, agent-aware flow import, cancellation during project-queue handoff, concurrency, and backup restoration.
- SQLite suite: **60 passed, 6 skipped**. The upgrade test includes a legacy published flow and conversation transcript and verifies association with its migrated project without changing direct-session behavior.
- The full migration chain and metadata-drift check passed on fresh SQLite and PostgreSQL databases.
- Browser checks with an isolated mock model confirmed routing a return request into an intent and the next request into a full agent, with both decisions shown in traces; Agent builder and Mini agents showed the same registered tool. The previous hidden “next” labels remain hidden.
- Live provider calls and Docker/RabbitMQ verification remain opt-in/environment-dependent as documented above.

## One-command local demo

`npm run dev` was exercised with the isolated demo profile. Browser sign-in using `demo@openccai.local` / `OpenCCAI-Demo123!` succeeded, and the sample Orders specialist used the mock shared tool to answer a fictional order lookup without API keys. The launcher selected an available console port while another application was running on 5173.

The SQLite suite passed **64 tests** with six environment-specific skips; both production builds and the two widget tests passed. Additional checks cover seed idempotence, persistence of playground edits, normal startup having no demo account, delegation of real model connections, separate private demo keys, and ignoring an inherited production database URL. Ctrl+C shutdown was verified for the API, worker, and console together.
