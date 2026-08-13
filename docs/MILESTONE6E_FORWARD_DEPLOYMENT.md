# Milestone 6E — Forward Research Deployment Kit

This milestone prepares the paper/shadow research system for an unattended VPS run. It does **not** enable real trading.

## Security posture

- `SIGNER_ENABLED=false` is forced by both launchers and the Compose overlay.
- PostgreSQL and Redis are not published to the host network.
- The API is bound to `127.0.0.1:8000`, not the public internet.
- Database and forward-ingest secrets are required and have no committed defaults.
- Provider credentials are research/data credentials only; wallet keys are not part of this deployment.
- The owner vault remains outside the VPS.

## Phase 1 — VPS burn-in

```bash
cp deploy/.env.forward.example deploy/.env.forward
# replace both required secrets
sh deploy/start-forward.sh
```

The burn-in launcher starts:

- PostgreSQL
- Redis
- Alembic migration job
- API / read-only `/forward/ops` observability
- Hyperliquid public-data collector
- Polymarket public structural collector
- six-hour PostgreSQL backup loop

It deliberately does **not** start `hyperliquid-forward-bootstrap`, `hyperliquid-forward-runner`, or `forward-evaluator`. Therefore no frozen study exists yet and the official forward-study clock has not started.

Keep this infrastructure healthy for at least 24 hours and verify backup/restore before beginning the official study.

## Phase 2 — official frozen study

After burn-in succeeds:

```bash
sh deploy/start-study.sh
```

The study launcher:

1. rechecks required secrets and refuses `SIGNER_ENABLED != false`;
2. runs the idempotent frozen Hyperliquid bootstrap;
3. records the exact initial simulated NAV/start time on first creation;
4. starts the operational paper/shadow runner;
5. starts the recommendation-only daily evaluator.

The first successful bootstrap defines the official forward clock. Re-running `start-study.sh` does not reset that clock: the bootstrap reuses the existing external ID only when its immutable lineage, frozen study configuration and evaluation policy still match exactly.

## Forward study settings

`deploy/.env.forward.example` includes the default simulated study values. They are research values, not live allocations. The important defaults are:

```text
HYPERLIQUID_FORWARD_STUDY_EXTERNAL_ID=hyperliquid-btc-carry-m6c-v1
HYPERLIQUID_FORWARD_INITIAL_CAPITAL_USD=1000
HYPERLIQUID_FORWARD_PAIRED_NOTIONAL_USD=100
HYPERLIQUID_FORWARD_HORIZON_HOURS=24
HYPERLIQUID_FORWARD_PLANNED_LOSS_PCT=0.02
```

Changing frozen values after a study exists causes bootstrap failure rather than retroactively changing the research record. Start a new external study/version when the strategy or experiment definition genuinely changes.

## Health and observability

Human/read-only API inspection remains available on loopback through:

- `GET /forward/ops/summary`
- `GET /forward/ops/incidents`
- `GET /forward/ops/positions`

The forward runner additionally has a database-backed container health check using:

```text
python -m app.forward_ops status --require-ready --quiet
```

A recorded data-integrity failure permanently blocks new evidence generation for that study. An unresolved non-integrity critical incident pauses it until explicitly resolved.

## Backup

Automatic local VPS backups run every six hours and retain 14 days. They are a first layer only; production operations should additionally copy encrypted backups off the VPS.

Manual backup:

```bash
sh deploy/backup-now.sh
```

## Network exposure

The Compose deployment intentionally exposes only the API on loopback. If remote viewing is later needed, put an authenticated tunnel/reverse proxy in front of it; do not expose PostgreSQL, Redis, or the raw API directly.

## Before starting the 90-day clock

1. Run `deploy/start-forward.sh` and confirm burn-in services stay healthy for at least 24 hours.
2. Verify automatic backups can be restored to a disposable database.
3. Review the study values in `deploy/.env.forward` one final time.
4. Confirm the signer setting is absent or exactly `false`.
5. Run `deploy/start-study.sh` once.
6. Confirm `/forward/ops/summary` and `python -m app.forward_ops status` show the newly frozen study.
7. Record the bootstrap start timestamp as the official forward-study start.

No result from this deployment can authorize capital or enable a signer. Promotion remains an evidence recommendation only.
