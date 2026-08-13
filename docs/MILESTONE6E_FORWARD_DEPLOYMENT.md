# Milestone 6E — Forward Research Deployment Kit

This milestone prepares the paper/shadow research system for an unattended VPS run. It does **not** enable real trading.

## Security posture

- `SIGNER_ENABLED=false` is forced by the launcher and Compose overlay.
- PostgreSQL and Redis are not published to the host network.
- The API is bound to `127.0.0.1:8000`, not the public internet.
- Database and forward-ingest secrets are required and have no committed defaults.
- Provider credentials are research/data credentials only; wallet/signing keys are not part of this deployment.
- The owner vault remains outside the VPS.

## VPS start

```bash
cp deploy/.env.forward.example deploy/.env.forward
# replace both required secrets
sh deploy/start-forward.sh
```

The forward profile starts:

- PostgreSQL
- Redis
- Alembic migration job
- API / read-only observability
- Hyperliquid public-data collector
- idempotent frozen Hyperliquid forward-study bootstrap
- operational Hyperliquid funding/carry paper-shadow runner
- Polymarket public structural collector
- idempotent frozen Polymarket structural forward-study bootstrap
- operational Polymarket immediate-structural paper-shadow runner
- shared daily recommendation-only forward evaluator
- six-hour PostgreSQL backup loop

The hardened overlay supplies the same secret-derived PostgreSQL URL to both venue bootstraps, both venue runners, and the evaluator. Every forward service explicitly keeps `SIGNER_ENABLED=false`.

Each venue runner depends on its own successful one-shot bootstrap. The shared evaluator depends only on successful database migration, so a failed or intentionally disabled venue bootstrap cannot suppress evidence scoring for another already-active study.

Solana workers remain a separate opt-in profile because Helius/Jupiter provider credentials and throughput decisions are not required for the Hyperliquid or Polymarket forward studies.

## Health checks

Hyperliquid runner readiness:

```bash
python -m app.forward_ops status \
  --external-id hyperliquid-btc-carry-m6c-v1 \
  --require-ready
```

Polymarket runner readiness:

```bash
python -m app.polymarket_forward_ops status \
  --external-id polymarket-structural-m6f-v1 \
  --require-ready
```

Both checks are database/read-only operational checks. They do not submit an order or require a signer. Docker uses each venue-specific command as that runner's healthcheck.

## Backup

Automatic local VPS backups run every six hours and retain 14 days. They are a first layer only; production operations should additionally copy encrypted backups off the VPS.

Manual backup:

```bash
sh deploy/backup-now.sh
```

## Network exposure

The Compose deployment intentionally exposes only the API on loopback. If remote viewing is later needed, put an authenticated tunnel/reverse proxy in front of it; do not expose PostgreSQL, Redis, or the raw API directly.

## Before a forward clock is trusted

For each enabled venue study:

1. Deploy and confirm its containers remain healthy for at least 24 hours.
2. Verify automatic backups can be restored to a disposable database.
3. Confirm the idempotent bootstrap created the immutable strategy/version/experiment and frozen study exactly once.
4. Confirm the venue-specific `status --require-ready` command reports ready after the worker has produced its required fresh evidence/heartbeat.
5. Confirm `/forward/ops/summary` shows the expected study/NAV evidence and no unresolved data-integrity incident.
6. Confirm the shared forward evaluator is producing recommendation-only audit rows without changing `Strategy.status`.
7. Only then rely on the stored study start timestamp for the intended evidence horizon.

No result from this deployment can authorize capital or enable a signer. Promotion remains an evidence recommendation only.
