# Milestone 6E — Forward Research Deployment Kit

This milestone prepares the paper/shadow research system for an unattended VPS run. It does **not** enable real trading.

## Security posture

- `SIGNER_ENABLED=false` is forced by the launchers and Compose overlays.
- PostgreSQL and Redis are not published to the host network.
- The API is bound to `127.0.0.1:8000`, not the public internet.
- Database and forward-ingest secrets are required and have no committed defaults.
- Provider credentials are research/data credentials only; wallet/signing keys are not part of this deployment.
- The owner vault remains outside the VPS.
- Solana uses Helius data plus Jupiter price-only `/order` requests without a taker; there is no `/execute` path in Edge Lab.
- Dashboard V1 is read-only and can be exposed only through the separate authenticated Cloudflare Tunnel layer.

## VPS preparation and preflight

```bash
cp deploy/.env.forward.example deploy/.env.forward
chmod 600 deploy/.env.forward
# replace the required secrets and research API keys
sh deploy/preflight-forward.sh
```

The default preflight includes the authenticated dashboard deployment and therefore requires `CLOUDFLARE_TUNNEL_TOKEN`. To validate only the private research stack before the Cloudflare tunnel exists:

```bash
sh deploy/preflight-forward.sh --research-only
```

Preflight does **not** start a trade or enable a signer. It fails closed when:

- Docker/Compose or Python are unavailable;
- the real environment file is missing or has loose Linux permissions;
- wallet/private-key/seed variables are found in the deployment environment;
- required PostgreSQL, ingest, Helius or Jupiter credentials are missing;
- required secrets still contain example placeholders or are below minimum length;
- `SIGNER_ENABLED` is not exactly false;
- the real environment/backup paths are not gitignored;
- the full Compose stack does not render;
- an expected research service is missing;
- PostgreSQL or Redis acquires a host port;
- the API stops being loopback-only;
- any critical forward service stops forcing signing off; or
- the dashboard tunnel receives database/provider credentials or publishes a host port.

The rendered Compose JSON contains interpolated secrets, so preflight keeps it in an in-memory pipe to its validation process and never writes or echoes it.

## VPS start

After preflight passes:

```bash
sh deploy/start-forward.sh
```

The research launcher composes:

- `docker-compose.yml`
- `deploy/compose.forward.yml`
- `deploy/compose.solana-forward.yml`

The forward research stack starts:

- PostgreSQL
- Redis
- Alembic migration job
- API / read-only observability and Dashboard V1
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

## Hosted dashboard start

Configure the owner-only Cloudflare Access application and remotely managed tunnel as described in `docs/DASHBOARD_V1.md`, including a Published Application origin of `http://api:8000`. Then:

```bash
sh deploy/start-dashboard-tunnel.sh
```

The tunnel is deliberately a separate launcher. Stopping public dashboard access therefore does not stop the private research workers.

## Runtime verification

Basic verification after the containers have started:

```bash
sh deploy/verify-forward.sh
```

Include the tunnel container in the check:

```bash
sh deploy/verify-forward.sh --with-dashboard
```

Basic verification requires the expected long-running research services, the loopback dashboard page/assets, and the dashboard's hard safety flags:

- `can_trade_live=false`
- `can_sign=false`
- `can_move_funds=false`
- `vault_accessible=false`
- `signer_enabled=false`

After enough initial market/evidence heartbeats have been produced, use strict verification:

```bash
sh deploy/verify-forward.sh --with-dashboard --strict
```

Strict mode additionally executes each venue's database/read-only `status --require-ready` command inside its own runner container. It still cannot submit an order or sign anything.

## Individual health checks

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

Dashboard V1 is now part of the FastAPI service at `/dashboard`. The Compose deployment exposes the API to the VPS host only on loopback. PostgreSQL, Redis, collectors and forward workers stay private.

The separate `cloudflared` Compose overlay reaches `http://api:8000` through the private Docker network and publishes no host port. Internet access must pass through an owner-only Cloudflare Access application. Do not publish the raw API or dashboard directly to the internet.

## Before a forward clock is trusted

For each enabled venue study:

1. Pass `sh deploy/preflight-forward.sh` before startup.
2. Deploy and confirm its containers remain healthy for at least 24 hours.
3. Verify automatic backups can be restored to a disposable database.
4. Confirm the idempotent bootstrap created the immutable strategy/version/experiment and frozen study exactly once.
5. Confirm the venue-specific `status --require-ready` command reports ready after the worker has produced its required fresh evidence/heartbeat.
6. Confirm `/forward/ops/summary` and Dashboard V1 show the expected study/NAV evidence and no unresolved data-integrity incident.
7. Confirm the shared forward evaluator is producing recommendation-only audit rows without changing `Strategy.status`.
8. Pass `sh deploy/verify-forward.sh --with-dashboard --strict` when the dashboard tunnel is enabled.
9. Only then rely on the stored study start timestamp for the intended evidence horizon.

No result from this deployment can authorize capital or enable a signer. Promotion remains an evidence recommendation only.
