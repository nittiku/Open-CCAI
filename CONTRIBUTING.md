# Contributing to Open-CCAI

Contributions are welcome under Apache-2.0. Use issues for bug reports and design proposals; never include API keys or customer transcripts in public reports.

1. Follow the local development instructions in README.md.
2. Keep changes focused and add behavioral tests for runtime, permission, persistence, or API changes.
3. Run `npm run build` and `.venv/bin/pytest backend/tests -q`.
4. For database/locking changes, also run tests against a disposable PostgreSQL+pgvector database using `TEST_DATABASE_URL`.
5. Add Alembic migrations for model changes and document API or deployment changes.

Provider integrations belong behind `ProviderAdapter`; channel integrations implement `ChannelAdapter`. Workflow definitions must remain portable JSON. Do not add license checks, mandatory telemetry, required hosted project services, or paid-only essential features.

Published flow versions are immutable. Never retry a non-idempotent external action merely because a worker lost its connection. Treat human ownership as authoritative over pending bot results.

Use a private report to the repository maintainers for security issues; if a private reporting channel is not configured, ask for one without disclosing exploit details publicly. Maintainers should enable GitHub private vulnerability reporting before a public release.
