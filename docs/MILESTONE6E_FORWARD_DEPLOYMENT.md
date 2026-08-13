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
- strict Hyperliquid funding/carry forward runner
- Polymarket public structural collector
- six-hour PostgreSQL backup loop

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
3. Register immutable strategy versions and experiments.
4. Create frozen forward studies with their evaluation policy/config snapshot.
5. Confirm `/forward/ops/summary` shows fresh NAV observations and no unresolved data-integrity incident.
6. Only then record the official forward-study start time.

No result from this deployment can authorize capital or enable a signer. Promotion remains an evidence recommendation only.
