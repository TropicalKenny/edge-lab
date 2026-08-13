# Milestone 6E — Forward Research Deployment Kit

This milestone prepares the paper/shadow research system for an unattended VPS run. It does **not** enable real trading.

## Security posture

- `SIGNER_ENABLED=false` is forced by the launchers and Compose overlays.
- PostgreSQL and Redis are not published to the host network.
- The internal research API is bound to `127.0.0.1:8000`, not the public Internet.
- Dashboard V1 uses a **separate** FastAPI gateway bound to `127.0.0.1:8080`.
- The dashboard uses PostgreSQL login `edge_dashboard`, with an **exact table allowlist and SELECT-only privileges**.
- `cloudflared` is attached only to `dashboard_gateway`; it shares no Docker network with the research API.
- The dashboard joins both `dashboard_gateway` and the private default network so it can read its allowlisted database tables.
- Cloudflare Tunnel reaches only the dashboard gateway at `http://dashboard:8080`.
- Database, dashboard and forward-ingest secrets are separate and have no committed real defaults.
- Provider credentials are research/data credentials only; wallet/signing keys are not part of this deployment.
- The owner vault remains outside the VPS.
- Solana uses Helius data plus Jupiter price-only `/order` requests without a taker; there is no `/execute` path in Edge Lab.

## VPS preparation and preflight

```bash
cp deploy/.env.forward.example deploy/.env.forward
chmod 600 deploy/.env.forward
# replace required secrets and research API keys
sh deploy/preflight-forward.sh
```

Normal preflight validates research services, the local isolated dashboard and the Cloudflare tunnel definition, so it requires `CLOUDFLARE_TUNNEL_TOKEN`. To validate the research stack plus local dashboard before a tunnel token exists:

```bash
sh deploy/preflight-forward.sh --research-only
```

Preflight does **not** start a trade or enable a signer. It fails closed when:

- Docker/Compose or Python are unavailable;
- the real environment file is missing or has loose Linux permissions;
- wallet/private-key/seed variables are found in deployment environment;
- PostgreSQL, ingest, dashboard, Helius or Jupiter credentials are missing;
- required secrets still contain examples, are below minimum length or reuse privileged secrets;
- `SIGNER_ENABLED` is not exactly false;
- environment/backup paths are not gitignored;
- the full Compose stack does not render;
- an expected research/dashboard service is missing;
- PostgreSQL or Redis acquires a host port;
- research API stops being loopback-only on 8000;
- dashboard stops being loopback-only on 8080;
- dashboard stops using the dedicated `edge_dashboard` identity;
- dashboard receives provider/ingest credentials;
- dashboard database bootstrap broadens access beyond the exact table SELECT allowlist or contains a write grant;
- any critical forward/dashboard service stops forcing signing off;
- cloudflared receives database/provider credentials or publishes a host port;
- cloudflared stops depending on the isolated dashboard gateway;
- cloudflared shares any Docker network with the research API.

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

The stack starts PostgreSQL, Redis, migrations, the private research API, the isolated dashboard gateway, all three public-data/forward research engines, the shared recommendation-only evaluator and the database backup loop.

The dashboard role bootstrap is one-shot. On every run it removes any earlier broad/default dashboard grants and grants SELECT only to:

- `strategies`
- `strategy_versions`
- `strategy_evaluation_runs`
- `forward_studies`
- `forward_nav_observations`
- `forward_study_incidents`
- `forward_trade_records`
- `forward_execution_records`

Future tables receive no automatic dashboard access.

Every forward service and dashboard explicitly keep `SIGNER_ENABLED=false`.

## Hosted dashboard start

Configure an **owner-only Cloudflare Access application** and remotely managed tunnel as described in `docs/DASHBOARD_V1.md`. The Published Application/Public Hostname origin must be:

```text
http://dashboard:8080
```

Then start the tunnel:

```bash
sh deploy/start-dashboard-tunnel.sh
```

The tunnel is deliberately separate. Stopping public dashboard access does not stop private research workers.

Do not configure the hostname to `api:8000`. The network topology also prevents cloudflared from directly reaching the API service: cloudflared is on `dashboard_gateway` only, while the research API is on the private default network.

## Runtime verification

Basic verification:

```bash
sh deploy/verify-forward.sh
```

Include the tunnel container:

```bash
sh deploy/verify-forward.sh --with-dashboard
```

Verification requires expected long-running research services plus the isolated dashboard. It verifies:

- dashboard health/page/assets on loopback 8080;
- internal research and documentation routes return 404 on the dashboard gateway;
- dashboard safety flags remain false and live capital remains `$0`;
- dashboard capital scope remains explicitly simulated;
- the actual PostgreSQL user is `edge_dashboard`;
- the dashboard can SELECT exactly the allowlisted tables and no others;
- the dashboard has no INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER table privilege;
- with the tunnel enabled, running cloudflared and research API containers share no Docker network.

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

## Before a forward clock is trusted

For each enabled venue study:

1. Pass `sh deploy/preflight-forward.sh` before startup.
2. Deploy and confirm containers remain healthy for at least 24 hours.
3. Verify automatic backups can be restored to a disposable database.
4. Confirm each idempotent bootstrap created its immutable strategy/version/experiment and frozen study exactly once.
5. Confirm each venue-specific `status --require-ready` command reports ready after required fresh evidence/heartbeats exist.
6. Confirm isolated Dashboard V1 shows expected simulated study/NAV evidence and no unresolved data-integrity incident.
7. Confirm the shared forward evaluator produces recommendation-only audit rows without changing `Strategy.status`.
8. Pass `sh deploy/verify-forward.sh --with-dashboard --strict` when the tunnel is enabled.
9. Only then rely on the stored study start timestamp for the intended evidence horizon.

No result from this deployment can authorize capital or enable a signer. Promotion remains an evidence recommendation only.
