# Architecture

## Processes and ownership

The console and widget communicate with FastAPI over `/api/v1` REST and authenticated WebSockets. The API records conversations, messages, events, and pending jobs in PostgreSQL in the same transaction. Celery is a delivery mechanism; the database job table is authoritative. A scheduler redispatches pending or expired jobs every three seconds. Workers are separate processes from the API.

A conversation pins an immutable workflow version, stores its current node and variables, and executes one bounded step per job. Input steps consume customer messages in arrival order. Published flows allow at most 200 nodes; executions stop after 200 steps per conversation to bound accidental cycles. AI nodes allow 1–8 model iterations, up to eight tool calls per model reply, a generation-loop budget of 75 seconds, and a 30-second maximum per model request. HTTP tool timeouts are 1–30 seconds. These execution guards are technical safeguards, not traffic licenses.

Workers acquire database job leases and lock the conversation while reserving a step. External model/tool calls happen outside that conversation lock. Heartbeats extend active leases; a crashed process stops extending its lease, allowing recovery after 180 seconds. Before applying results, workers recheck the job lease token, conversation revision, status, and step number. Human handoff/closure increments the revision, invalidating pending bot output. Bot chunks are suppressed once human ownership takes effect.

RabbitMQ messages can be duplicated. Finished jobs and stale lease results are ignored. Customer/agent sends use caller-supplied idempotency IDs scoped by conversation and author role. Recovery can repeat LLM generation and incur additional provider usage; it cannot promise exactly-once billing.

## External actions

HTTP tools use JSON Schema validation on inputs and outputs, HTTPS host allowlists, public-address DNS checks, disabled redirects/proxies, bounded responses, and separate encrypted bearer credentials. Each action has a durable invocation identifier, also sent as `Idempotency-Key`.

A succeeded invocation reuses its stored result. A previously started action is repeated only when its registered contract explicitly guarantees idempotency. Otherwise its outcome becomes uncertain and the workflow follows its error branch. Agents see uncertain invocation identifiers and must check the external system before manually repeating an action. The platform does not claim exactly-once effects across an arbitrary external API.

The application checks destinations before connecting. Enforce an infrastructure egress policy as well: application DNS checks alone cannot prevent every DNS rebinding or network-routing attack. Only administrators can register endpoints and secrets.

## Providers and knowledge

`ProviderAdapter` normalizes generation, streaming, tool calling, structured output, embeddings, and errors. `LiteLLMAdapter` supplies the initial implementations without a proxy. Capability declarations are explicit connection settings and must match the selected model; unsupported configured capabilities fail validation. There is no automatic cross-provider fallback.

Generation and embedding models are separate connections. Connections are immutable records; keys can rotate independently. Knowledge is bot-scoped. Each collection has an embedding-profile fingerprint and generation. Reindexing increments its generation immediately, excluding stale chunks until new ingestion succeeds. Workers recheck the generation after external embedding calls; deletion/reindexing wins over stale results.

Uploaded files live behind a storage protocol with a local-volume implementation. UTF-8 documents and text PDFs are split into overlapping 1,800-character chunks with 300-character overlap. The initial implementation uses exact cosine retrieval through pgvector, then merges the top results across selected collections. It does not yet build ANN indexes; benchmark before increasing corpus size. Retrieved text is untrusted context, not executable instructions. Answers include retrieved document references; references alone are not proof that every generated statement is grounded.

Provider failures are normalized without exposing raw provider exception payloads. Successful model calls record generation token usage/latency even if a later tool or iteration fails. Embedding usage is not currently included in token totals. Cost is an optional configured estimate in the organization's chosen billing currency.

## Channels, real-time events, and roles

`ChannelAdapter` defines shared inbound messages and outbound representations; website chat is the initial implementation. Future channels must reuse conversation ownership and idempotency rather than build parallel agent state.

WebSockets authenticate in their first frame, never through URL tokens. Dashboard sockets use the HTTP-only session cookie. Widget sockets use a bot/conversation/origin-bound, expiring capability. A reconnect starts with persisted history; transient partial model output is not the durable transcript. Event polling includes a replay window and event-ID deduplication; periodic persisted snapshots reconcile messages and ownership even if a transient event is missed. Initial conversation capabilities expire after 24 hours; dashboard sessions expire after eight hours.

Administrators manage installation settings, users, secrets, connections, tools, queues, bots, and operations. Builders manage bots and knowledge and inspect execution history, but cannot read secrets or access the operational conversation list. Agents handle conversations; supervisors also monitor and close conversations. Roles apply across the single organization's workspace. Per-bot team ACLs, queue membership restrictions, SSO, and tenant isolation are future work.

Closure, handoff, and evidenced resolution are distinct. The initial platform records closure and handoff; it does not infer successful resolution from a closed conversation.

## Project orchestration

Projects have independently published routing catalogs and full-agent definitions. Conversations may execute the project orchestrator, a pinned intent/flow, or a pinned full agent. The runtime persists each transition using the same leases, ownership checks, messages, and transactional jobs as direct flows. Flow completion and full-agent replies return to the orchestrator; direct legacy sessions still close on end nodes. Mini agents and full agents share `agent_execution.py` and the existing HTTP-tool executor. See [orchestration](orchestration.md) for request consumption, version pinning, knowledge boundaries, and widget capability scope.
