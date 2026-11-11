# Operations

## Before exposing the installation

Terminate TLS at a reverse proxy, preserve WebSocket upgrades, set `APP_ORIGINS` to the exact console origin, and set `SECURE_COOKIE=true`. Local configuration uses insecure cookies only for localhost HTTP. Keep database, broker, and API services on private networks. The Compose console binds to `127.0.0.1` by default; publish through your own reverse proxy.

Back up `.env` securely. `ENCRYPTION_KEY` decrypts stored credentials; losing it makes the keys unrecoverable. `APP_SECRET` signs session and widget capabilities; changing it invalidates existing sessions. Rotate provider credentials through the console without changing the encryption key. Installation setup is single-use and protected by `SETUP_TOKEN`. Invitations expire in 24 hours and are usable once; administrators deliver links themselves.

Set `TOOL_ALLOWED_HOSTS` and `PROVIDER_ALLOWED_HOSTS` to exact hostnames as needed. Tools require public HTTPS endpoints on port 443. Private HTTP endpoints/local model servers are not supported by the default outbound policy. An organization can expose an appropriately protected HTTPS gateway or implement its own reviewed adapter. Avoid forwarding arbitrary workflow-controlled URLs to your internal network.

Disable access logging at any upstream proxy for URLs that may contain invitation tokens. The included nginx disables access logging, and the API does not log request paths. Review third-party SDK logging configuration before enabling debug logs.

## Lifecycle and diagnostics

```sh
docker compose ps
docker compose logs --tail=100 api worker scheduler
docker compose exec api alembic current
curl --fail http://localhost:8080/api/v1/health
```

`/health` verifies API/database connectivity. Worker and scheduler health must be checked separately: verify greeting delivery in a test conversation and inspect oldest pending jobs. The scheduler must have exactly one active instance per deployment. Jobs stuck in `running` after a crash recover after their lease expires. A queue with no available agents stays visibly queued; the bot does not claim a transfer was accepted.

The dashboard shows lifetime conversation counts, queue waiting times, handoffs, and generation usage/errors from the most recent 1,000 traces. Agent lists show the latest 200 conversations. Cost estimates require configured per-million-token input/output prices. They do not include embedding costs and are not billing reconciliation.

Uploaded source files and transcripts can contain personal information. Set retention, access, encryption-at-rest, filesystem/volume backup, and incident-handling policies for your deployment. Source uploads use owner-only file permissions; database and uploaded-volume encryption depend on the host/storage configuration. There is no automatic retention deletion job in this release. Event/trace/job storage grows with use; monitor disk space and establish an audited archival policy before sustained production traffic.

## Backup and restore

Use a trusted local path outside the checkout. The backup includes customer data and encryption/signing keys.

```sh
sh scripts/backup.sh /absolute/private/path/ccai-backup
```

This stops API/workers/scheduler, creates a PostgreSQL custom-format dump, archives source documents, copies `.env` privately, writes checksums, and restarts the writers even if backup fails. There is a brief outage. It does not rely on copying a live database volume.

Restore into a **new checkout and empty Compose installation**, with the same project version first:

```sh
sh scripts/restore.sh /absolute/private/path/ccai-backup
```

Restore refuses an existing `.env` or populated database. Keep the original `ENCRYPTION_KEY`. If the new deployment uses another hostname, update `APP_ORIGINS`, bot website origins, and TLS configuration before exposing it. Verify login, encrypted credential use, uploaded document retrieval, transcript history, and a new bot-to-agent journey. Recovery scripts are supplied; Docker-based restore verification is part of the release validation process, not assumed from a successful file copy.

## Updating and capacity

Take a backup before upgrades. Review migration changes, then rebuild and recreate services; the migration job must rerun for a new release (`docker compose run --rm migrate`) before starting changed application processes. Do not downgrade a live schema without restoring a compatible backup.

Run `scripts/load.py` against a disposable published bot with an allowed test origin to measure conversation creation and greeting delivery. This is a baseline smoke load, not a capacity certification. Test with your actual LLM latency, corpus sizes, handoff rate, concurrent sockets, external tools, and host resources. The initial stack has one database and one server; high availability, cross-host object storage, retention automation, large-scale event fanout, and production sizing remain deployment work.
