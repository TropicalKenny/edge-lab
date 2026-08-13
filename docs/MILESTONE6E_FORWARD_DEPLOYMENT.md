# Milestone 6E — Forward Research Deployment Kit

This milestone prepares the existing paper/shadow research system for an unattended VPS run. It does **not** enable real trading.

## Security posture

- `SIGNER_ENABLED=false` is forced by the launcher and Compose overlay.
- PostgreSQL and Redis are not published to the host network.
- The API is bound to `127.0.0.1:8000`, not the public internet.
- Database and forward-ingest secrets are required and have no committed defaults.
- Provider credentials are research/data credentials only; wallet keys are not part of this deployment.
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
- daily recommendation-only forward evaluator
- Polymarket public structural collector
- six-hour PostgreSQL backup loop

The hardened overlay supplies the same secret-derived PostgreSQL URL to the bootstrap, runner and evaluator. The launcher explicitly includes the bootstrap and evaluator, so the VPS deployment cannot accidentally run a forward worker without registering its frozen study or omit daily evidence scoring.

Solana workers remain a separate opt-in profile because Helius/Jupiter provider credentials and throughput decisions are not required to begin the Hyperliquid forward study.

## Backup

Automatic local VPS backups run every six hours and retain 14 days. They are a first layer only; production operations should additionally copy encrypted backups off the VPS.

Manual backup:

```bash
sh deploy/backup-now.sh
```

## Network exposure

The Compose deployment intentionally exposes only the API on loopback. If remote viewing is later needed, put an authenticated tunnel/reverse proxy in front of it; do not expose PostgreSQL, Redis, or the raw API directly.

## Before the 90-day clock starts

1. Deploy and confirm containers stay healthy for at least 24 hours.
2. Verify automatic backups can be restored to a disposable database.
3. Confirm the idempotent bootstrap created the immutable strategy/version/experiment and frozen study exactly once.
4. Confirm `python -m app.forward_ops status --require-ready` reports the study ready after fresh market observations arrive.
5. Confirm `/forward/ops/summary` shows fresh NAV observations and no unresolved data-integrity incident.
6. Confirm the forward evaluator is producing recommendation-only audit rows without changing `Strategy.status`.
7. Only then treat the stored study start timestamp as the official forward-research clock.

No result from this deployment can authorize capital or enable a signer. Promotion remains an evidence recommendation only.
