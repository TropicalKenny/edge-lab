# Milestone 1 — Quant Core

## Delivered

- PostgreSQL-compatible SQLAlchemy schema and initial Alembic migration.
- Double-entry portfolio ledger with balance and NAV calculations.
- Deterministic fail-closed risk service.
- Correlation-bucket exposure checks.
- Immutable/versioned experiment registry primitives.
- Paper Engine V2 with depth walking, partial fills, fees, latency and rejection states.
- Shadow broker interface that records executable quotes without signing.
- Disabled signer implementation.
- Health and incident models.
- FastAPI endpoints for health, risk evaluation, paper simulation and signer status.
- Docker Compose stack for API, PostgreSQL and Redis.
- Unit/integration tests for critical invariants.

## Explicitly absent

- No wallet/private key storage.
- No transaction signing.
- No venue order submission.
- No bridge execution.
- No live market collectors.
- No live profitability or GREEN claims.

## Exit criteria

Milestone 1 is complete when all tests pass and venue adapters can consume the common models
without bypassing risk or accounting.
