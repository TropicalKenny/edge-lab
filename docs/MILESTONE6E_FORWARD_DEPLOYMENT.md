# Milestone 6E — Forward Research Deployment Kit

This milestone prepares the paper/shadow research system for an unattended VPS run. It does **not** enable real trading.

## Security posture

- `SIGNER_ENABLED=false` is forced by the launchers and Compose overlays.
- PostgreSQL and Redis are not published to the host network.
- The internal research API is bound to `127.0.0.1:8000`, not the public internet.
- Dashboard V1 uses a **separate** FastAPI gateway bound to `127.0.0.1:8080` and a PostgreSQL `edge_dashboard` **SELECT-only** login.
- Cloudflare Tunnel must reach only the dashboard gateway at `http://dashboard:8080` on the private Compose network.
- Database, dashboard and forward-ingest secrets are separate and have no committed real defaults.
- Provider credentials are research/data credentials only; wallet/signing keys are not part of this deployment.
- The owner vault remains outside the VPS.
- Solana uses Helius data plus Jupiter price-only `/order` requests without a taker; there is no `/execute` path in Edge Lab.

## VPS preparation and preflight

```bash
cp deploy/.env.forward.example deploy/.env.forward
chmod 600 deploy/.env.forward
# replace the required secrets and research API keys
sh deploy/preflight-forward.sh
```

The normal preflight validates research services, the local isolated dashboard, and the Cloudflare tunnel definition. It therefore requires `CLOUDFLARE_TUNNEL_TOKEN`. To validate the private research stack plus local dashboard before a tunnel token exists:

```bash
sh deploy/preflight-forward.sh --research-only
```

Preflight does **not** start a trade or enable a signer. It fails closed when:

- Docker/Compose or Python are unavailable;
- the real environment file is missing or has loose Linux permissions;
- wallet/private-key/seed variables are found in the deployment environment;
- PostgreSQL, ingest, dashboard, Helius or Jupiter credentials are missing;
- required secrets still contain example placeholders, are below minimum length, or the dashboard database secret reuses a privileged secret;
- `SIGNER_ENABLED` is not exactly false;
- the real environment/backup paths are not gitignored;
- the full Compose stack does not render;
- an expected research/dashboard service is missing;
- PostgreSQL or Redis acquires a host port;
- the research API stops being loopback-only on port 8000;
- the dashboard stops being loopback-only on port 8080;
- the dashboard stops using the dedicated `edge_dashboard` database identity;
- any critical forward/dashboard service stops forcing signing off;
- cloudflared receives database/provider credentials, publishes a host port, depends on the research API, or stops depending on the isolated dashboard service.

Rendered Compose JSON contains interpolated secrets, so preflight keeps it in an in-memory pipe and never writes or echoes it.

## VPS start

After preflight passes:

```bash
sh deploy/start-forward.sh
```

The launcher composes:

- `docker-compose.yml`
- `deploy/compose.forward.yml`
- `deploy/compose.solana-forward.yml`
- `deploy/compose.dashboard.yml`

The stack starts PostgreSQL, Redis, migrations, the private research API, the isolated dashboard gateway, all three public-data/forward research engines, the shared recommendation-only evaluator, and the database backup loop. The dashboard role bootstrap is a one-shot service that grants SELECT only.

Every forward service and the dashboard explicitly keep `SIGNER_ENABLED=false`.

## Hosted dashboard start

Configure an **owner-only Cloudflare Access application** and remotely managed tunnel as described in `docs/DASHBOARD_V1.md`. The Published Application/Public Hostname origin must be:

```text
http://dashboard:8080
```

Then start the tunnel:

```bash
sh deploy/start-dashboard-tunnel.sh
```

The tunnel is deliberately separate. Stopping public dashboard access therefore does not stop private research workers. Never configure the public hostname to the internal `api:8000` service.

## Runtime verification

Basic verification:

```bash
sh deploy/verify-forward.sh
```

Include the tunnel container:

```bash
sh deploy/verify-forward.sh --with-dashboard
```

Verification requires the expected long-running research services plus the isolated dashboard gateway. It checks the dashboard health/page/assets and the hard safety flags:

- `can_trade_live=false`
- `can_sign=false`
- `can_move_funds=false`
- `vault_accessible=false`
- `signer_enabled=false`

It also verifies an internal forward route returns 404 on the dashboard gateway.

After initial market/evidence heartbeats exist, use strict verification:

```bash
sh deploy/verify-forward.sh --with-dashboard --strict
```

Strict mode additionally runs the existing database/read-only readiness commands for Hyperliquid, Polymarket and Solana. It still cannot submit an order or sign anything.

## Individual health checks

Hyperliquid:

```bash
python -m app.forward_ops status --external-id hyperliquid-btc-carry-m6c-v1 --require-ready
```

Polymarket:

```bash
python -m app.polymarket_forward_ops status --external-id polymarket-structural-m6f-v1 --require-ready
```

Solana:

```bash
python -m app.solana_forward_ops status --external-id solana-pump-baseline-m6g-v1 --require-ready
```

All three are database/read-only operational checks. Docker uses each venue-specific command as that runner's healthcheck.

## Backup

Automatic local VPS backups run every six hours and retain 14 days. They are a first layer only; production operations should additionally copy encrypted backups off the VPS.

Manual backup:

```bash
sh deploy/backup-now.sh
```

## Network exposure and dashboard

Dashboard V1 is served publicly only by `app.dashboard_server` on the private `dashboard:8080` service. The research API remains a separate private process on loopback port 8000. PostgreSQL, Redis, collectors and forward workers stay private.

The `cloudflared` container depends on the healthy dashboard service, publishes no host port, receives only its tunnel credential, and must be protected by the owner-only Cloudflare Access application.

## Before a forward clock is trusted

For each enabled venue study:

1. Pass `sh deploy/preflight-forward.sh` before startup.
2. Deploy and confirm containers remain healthy for at least 24 hours.
3. Verify automatic backups can be restored to a disposable database.
4. Confirm each idempotent bootstrap created its immutable strategy/version/experiment and frozen study exactly once.
5. Confirm each venue-specific `status --require-ready` command reports ready after required fresh evidence/heartbeats exist.
6. Confirm the isolated Dashboard V1 shows expected study/NAV evidence and no unresolved data-integrity incident.
7. Confirm the shared forward evaluator produces recommendation-only audit rows without changing `Strategy.status`.
8. Pass `sh deploy/verify-forward.sh --with-dashboard --strict` when the tunnel is enabled.
9. Only then rely on the stored study start timestamp for the intended evidence horizon.

No result from this deployment can authorize capital or enable a signer. Promotion remains an evidence recommendation only.
