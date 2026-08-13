# Milestone 6E — Forward Research Deployment Kit

This milestone prepares the paper/shadow research system for an unattended VPS run. It does **not** enable real trading.

## Security posture

- `SIGNER_ENABLED=false` is forced by the launcher and Compose overlays.
- PostgreSQL and Redis are not published to the host network.
- The API is bound to `127.0.0.1:8000`, not the public internet.
- Database and forward-ingest secrets are required and have no committed defaults.
- Provider credentials are research/data credentials only; wallet/signing keys are not part of this deployment.
- The owner vault remains outside the VPS.
- Solana uses Helius data plus Jupiter price-only `/order` requests without a taker; there is no `/execute` path in Edge Lab.

## VPS start

```bash
cp deploy/.env.forward.example deploy/.env.forward
# replace the required secrets and research API keys
sh deploy/start-forward.sh
```

The launcher now composes three files:

- `docker-compose.yml`
- `deploy/compose.forward.yml`
- `deploy/compose.solana-forward.yml`

The forward research stack starts:

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
- Helius chain-native Solana Pump launch collector
- bounded Solana forensic enrichment sampler
- idempotent frozen Solana Pump baseline forward-study bootstrap
- operational Solana quote-only paper-shadow runner
- shared daily recommendation-only forward evaluator
- six-hour PostgreSQL backup loop

The hardened overlays supply the same secret-derived PostgreSQL URL to all bootstraps/runners and the evaluator. Every forward service explicitly keeps `SIGNER_ENABLED=false`.

Each venue runner depends on its own successful one-shot bootstrap. The shared evaluator depends only on successful database migration, so a failed or intentionally disabled venue bootstrap cannot suppress evidence scoring for another already-active study.

The Solana forward stack requires `HELIUS_API_KEY` and `JUPITER_API_KEY`. These are research/API credentials, not wallet keys. `GOPLUS_ACCESS_TOKEN` remains optional; if required security evidence cannot be obtained, that candidate simply cannot qualify for the baseline entry policy.

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

Solana runner readiness:

```bash
python -m app.solana_forward_ops status \
  --external-id solana-pump-baseline-m6g-v1 \
  --require-ready
```

All three checks are database/read-only operational checks. They do not submit an order or require a signer. Docker uses each venue-specific command as that runner's healthcheck.

The Solana health check additionally fails closed on corrupted open-position journal metadata, frozen lineage mismatch, permanent data-integrity contamination, unresolved critical incidents, missing initial NAV, or a stale executable-liquidation NAV heartbeat.

## Backup

Automatic local VPS backups run every six hours and retain 14 days. They are a first layer only; production operations should additionally copy encrypted backups off the VPS.

Manual backup:

```bash
sh deploy/backup-now.sh
```

## Network exposure and dashboard

The Compose deployment intentionally exposes only the API on loopback. PostgreSQL, Redis, collectors and forward workers stay private.

The planned Dashboard V1 will sit in front of this private backend and be exposed through an authenticated tunnel/reverse proxy (for example Cloudflare Tunnel + Access), so the owner can monitor Edge Lab from phone/tablet/laptop without exposing the internal services. Until that dashboard is added, do not publish the raw API directly to the internet.

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
