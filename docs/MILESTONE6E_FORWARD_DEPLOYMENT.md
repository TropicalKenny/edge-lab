# Milestone 6E — Forward Research Deployment Kit

This milestone prepares the paper/shadow research system for an unattended VPS run. It does **not** enable real trading.

## Security posture

- `SIGNER_ENABLED=false` is forced by launchers and Compose overlays.
- PostgreSQL and Redis publish no host ports.
- The internal research API is bound only to `127.0.0.1:8000`.
- Dashboard V1 uses a separate dashboard-only FastAPI surface reachable by Cloudflare at `http://dashboard:8080`.
- Cloudflared is attached only to `dashboard_edge` and shares no Docker network with the research API.
- The dashboard uses the separate `edge_dashboard` PostgreSQL identity with an **exact table allowlist and SELECT-only privileges**.
- Future database tables do not automatically become dashboard-readable.
- Database, dashboard and forward-ingest secrets are separate.
- Provider credentials are research/data credentials only; wallet/signing keys are absent.
- The owner vault remains outside the VPS.
- Solana uses Helius data plus Jupiter price-only `/order` requests without a taker; Edge Lab has no `/execute` path.
- All displayed dashboard capital is simulated research capital; live capital remains `$0`.

## VPS preparation and preflight

```bash
cp deploy/.env.forward.example deploy/.env.forward
chmod 600 deploy/.env.forward
# replace required secrets and research API keys
sh deploy/preflight-forward.sh
```

The default preflight includes the authenticated dashboard deployment and therefore requires `CLOUDFLARE_TUNNEL_TOKEN`. To validate only the private research stack before Cloudflare exists:

```bash
sh deploy/preflight-forward.sh --research-only
```

Both normal launchers also invoke their appropriate preflight automatically, so the normal startup path cannot silently skip the gate.

Preflight does **not** start a trade or enable a signer. It fails closed when, among other things:

- Docker/Compose or Python are unavailable;
- the real environment file is missing or has loose Linux permissions;
- wallet/private-key/seed variables are found;
- PostgreSQL, ingest, Helius or Jupiter credentials are missing;
- required secrets are weak, placeholders or reused across privileged boundaries;
- `SIGNER_ENABLED` is not exactly false;
- environment/backup paths are not gitignored;
- the full Compose stack does not render;
- PostgreSQL or Redis acquires a host port;
- the research API stops being loopback-only;
- the dashboard receives unexpected credentials;
- the dashboard stops using `edge_dashboard`;
- the dashboard DB bootstrap grants all/future-table SELECT or any write privilege;
- the dashboard DB role stops defaulting transactions to read-only;
- cloudflared receives anything other than its tunnel token;
- cloudflared leaves `dashboard_edge`, gains a host port or shares a Docker network with the research API.

Rendered Compose JSON contains interpolated secrets, so preflight keeps it in an in-memory pipe and never writes or echoes it.

## Private research start

```bash
sh deploy/start-forward.sh
```

The launcher first runs:

```bash
sh deploy/preflight-forward.sh --research-only
```

and then starts PostgreSQL, Redis, migrations, the private research API, all three public-data/forward research engines, the shared recommendation-only evaluator and the backup loop.

Each venue runner depends on its own successful one-shot bootstrap. The evaluator depends only on successful database migration, so one failed/disabled venue cannot suppress evidence scoring for another active study.

The Solana stack requires `HELIUS_API_KEY` and `JUPITER_API_KEY`. These are research/API credentials, not wallet keys. `GOPLUS_ACCESS_TOKEN` remains optional; missing required security evidence causes that candidate to be rejected rather than fabricated.

## Hosted dashboard start

Create the **owner-only Cloudflare Access application** first and configure the remotely managed tunnel as documented in `docs/DASHBOARD_V1.md`.

The public origin must be:

```text
http://dashboard:8080
```

Never use `api:8000`.

Then:

```bash
sh deploy/start-dashboard-tunnel.sh
```

That launcher itself runs the full `deploy/preflight-forward.sh` before starting `dashboard-db-role`, `dashboard` and `cloudflared`.

The tunnel is independent from the private research workers. Stopping public dashboard access does not stop research collection/evaluation.

## Dashboard database identity

Every dashboard bootstrap removes older broad/default grants and gives `edge_dashboard` SELECT only on:

- `strategies`
- `strategy_versions`
- `strategy_evaluation_runs`
- `forward_studies`
- `forward_nav_observations`
- `forward_study_incidents`
- `forward_trade_records`
- `forward_execution_records`

The role is non-superuser/non-creator/non-replication/non-bypass-RLS, defaults transactions to read-only and has short query/session timeouts.

No future table becomes readable automatically.

## Runtime verification

Basic private research verification:

```bash
sh deploy/verify-forward.sh
```

Include the hosted dashboard/tunnel:

```bash
sh deploy/verify-forward.sh --with-dashboard
```

With the dashboard enabled, verification proves:

- the exact Cloudflare-facing dashboard health surface is safe and DB-backed;
- dashboard summary is read-only, explicitly simulated and has `live_capital_usd=0`;
- signer/risk/paper/forward/portfolio/OpenAPI/docs internal paths are absent from the hosted surface;
- PostgreSQL current user is exactly `edge_dashboard`;
- the dashboard-readable table set equals the exact allowlist above;
- INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER are unavailable on every allowlisted table;
- runtime cloudflared and research API containers share no Docker network;
- cloudflared still shares the intended `dashboard_edge` network with the dashboard.

After initial evidence heartbeats exist, use:

```bash
sh deploy/verify-forward.sh --with-dashboard --strict
```

Strict mode additionally runs each venue's database/read-only `status --require-ready` command. It still cannot submit or sign an order.

## Individual forward health checks

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

All three are database/read-only operational checks. They do not require a signer.

## Backup

Automatic local VPS backups run every six hours and retain 14 days. They are a first layer; production should additionally copy encrypted backups off the VPS.

Manual backup:

```bash
sh deploy/backup-now.sh
```

## Before a forward clock is trusted

For each enabled venue study:

1. Pass preflight before startup.
2. Deploy and confirm containers remain healthy for at least 24 hours.
3. Verify automatic backups can be restored to a disposable database.
4. Confirm the idempotent bootstrap created immutable strategy/version/experiment/frozen study exactly once.
5. Confirm venue `status --require-ready` reports ready after required fresh evidence exists.
6. Confirm Dashboard V1 shows expected **simulated** study/NAV evidence and no data-integrity contamination.
7. Confirm the evaluator writes recommendation-only audit rows without changing `Strategy.status`.
8. Pass `sh deploy/verify-forward.sh --with-dashboard --strict`.
9. Only then rely on the stored study start timestamp for the intended evidence horizon.

No result from this deployment can authorize capital or enable a signer. Promotion remains an evidence recommendation only.
