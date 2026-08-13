# Dashboard V1 — Hosted Research Terminal

## Purpose

Dashboard V1 gives the owner a browser UI for Edge Lab while the research workers continue running on the VPS.

The UI is deliberately **read-only**. It displays forward-study NAV, evidence state, research P&L, trade/execution counts, incidents and recent closed paper trades. It cannot sign, submit venue orders, move funds, reach the owner vault, change strategy status, or authorize live capital.

All NAV/capital/P&L values are **simulated research values**. Each frozen forward study has its own independent simulated bankroll. The overview may add those bankrolls together for observability, but that aggregate is not a real portfolio/vault balance and is not deployable capital. Live capital is explicitly `$0`.

## Hosted surface

The internal research API and Internet-facing dashboard are separate ASGI surfaces:

```text
Owner browser
  -> Cloudflare Access
  -> Cloudflare Tunnel
  -> cloudflared (dashboard_edge network only)
  -> dashboard:8080
  -> edge_dashboard PostgreSQL role (exact-table SELECT-only)

Private research services
  -> api:8000 / host loopback 127.0.0.1:8000
  -> PostgreSQL / Redis / collectors / runners / evaluator
```

`app.dashboard_server` mounts Dashboard V1 plus `/healthz`. It does not mount signer, risk, paper simulation, venue, forward-operations, portfolio mutation or internal documentation/OpenAPI routes.

Cloudflared is attached only to `dashboard_edge`. The research API is not on that network, so a bad remotely-managed Cloudflare origin cannot directly resolve/reach `api:8000` from the cloudflared container.

**The correct Cloudflare origin is `http://dashboard:8080`. Do not point the tunnel at `api:8000`.**

## Database boundary

The hosted dashboard uses a separate PostgreSQL login named `edge_dashboard` with an exact-table **SELECT-only** policy.

Every dashboard bootstrap:

- makes the role non-superuser/non-creator/non-replication/non-bypass-RLS;
- defaults transactions to read-only;
- applies short statement/idle-transaction timeouts;
- removes any older broad/default table privileges;
- grants SELECT only to the exact Dashboard V1 table allowlist:
  - `strategies`
  - `strategy_versions`
  - `strategy_evaluation_runs`
  - `forward_studies`
  - `forward_nav_observations`
  - `forward_study_incidents`
  - `forward_trade_records`
  - `forward_execution_records`

It does **not** receive `SELECT ON ALL TABLES`, and future tables do not automatically become visible. This prevents a later wallet, treasury or other sensitive table from becoming readable merely because a migration creates it.

Runtime verification introspects PostgreSQL privileges and fails unless the readable table set is exactly the allowlist and INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER privileges are all unavailable.

## Cloudflare setup order

**Create the Cloudflare Access application before publishing the tunnel hostname.**

1. Create a Cloudflare Zero Trust **Self-hosted** Access application for the dashboard hostname, e.g. `edge.example.com`.
2. Add an **owner-only Allow policy**. Do not use Allow Everyone.
3. Require the desired identity-provider/MFA controls.
4. Create a remotely managed Cloudflare Tunnel.
5. Publish the hostname with origin URL **`http://dashboard:8080`**.
6. Do not point the tunnel at `api:8000`.
7. Enable **Protect with Access**.
8. Put only the generated Tunnel token into uncommitted `deploy/.env.forward` as `CLOUDFLARE_TUNNEL_TOKEN`.
9. Keep `DASHBOARD_DB_PASSWORD` separate from PostgreSQL and forward-ingest secrets.
10. Run:

```sh
sh deploy/preflight-forward.sh
sh deploy/start-forward.sh
sh deploy/start-dashboard-tunnel.sh
sh deploy/verify-forward.sh --with-dashboard --strict
```

11. Open `https://edge.example.com/dashboard` and confirm Cloudflare Access appears before Edge Lab.
12. From outside the VPS, confirm PostgreSQL, Redis and port 8000 are not publicly reachable.

The hostname is intentionally not hard-coded in the repository.

## Deployment safeguards

Normal launchers invoke preflight themselves:

- `start-forward.sh` runs the research-only preflight;
- `start-dashboard-tunnel.sh` runs the full dashboard/tunnel preflight.

Preflight rejects wallet/private-key material, unsafe signer state, placeholder/reused secrets, public database/dashboard ports, a non-loopback research API, broad dashboard database grants, unexpected dashboard/cloudflared credentials, or any Cloudflare network shared with the research API.

Runtime verification checks:

- exact dashboard health/safety state, including `live_capital_usd=0`;
- explicit `capital_scope=independent-simulated-forward-study-bankrolls`;
- internal dashboard routes are absent;
- exact PostgreSQL read allowlist and absence of table-write privileges;
- cloudflared and the research API share no Docker network;
- strict venue readiness when requested.

## Browser hardening

The isolated dashboard adds a same-origin CSP, frame blocking, MIME no-sniff, no-referrer policy, restrictive Permissions Policy, same-origin opener/resource policies, HSTS, no-index/no-archive and `Cache-Control: no-store`.

Its health endpoint fails closed when signing is enabled or its database connection is unavailable.

## UI information architecture

### Overview

- aggregate **simulated** forward-study NAV;
- return across independent frozen study bankrolls;
- closed research P&L;
- worst observed drawdown among independent study NAV series;
- active study count;
- unresolved incidents and permanent data-integrity contamination;
- NAV history chart per independent study;
- strategy cards;
- recent paper trades;
- explicit live-capital `$0`, signer/order/fund/vault safety state.

The aggregate simulated NAV is never owner-vault balance or real portfolio NAV.

### Strategies

Each frozen study shows version, family, venue, instrument, current simulated NAV, P&L, observed drawdown, elapsed forward days, trade count, shadow observations and latest recommendation/reasons.

`GREEN-1_CANDIDATE` remains evidence only. The UI cannot promote a strategy.

### Trades

Closed records are normalized simulated/shadow evidence, not live fills.

### Incidents

A study with **any** data-integrity incident remains contaminated even if that incident is later operationally resolved. Permanent integrity counts are separate from unresolved operational incidents.

## Mobile behavior

The dashboard is light-first, supports an optional local dark theme, collapses navigation to a fixed bottom bar on phones, uses horizontal scrolling only for dense tables, and has no hover-only dependency.

## Safety contract

The dashboard reports:

```json
{
  "can_trade_live": false,
  "can_sign": false,
  "can_move_funds": false,
  "vault_accessible": false,
  "signer_enabled": false,
  "live_capital_usd": 0
}
```

It identifies capital scope as `independent-simulated-forward-study-bankrolls` and adds no dashboard write routes.

The hosting layer grants neither Cloudflare nor the dashboard access to a wallet/private key, owner vault, venue signer or fund-transfer function.

## Next UI milestone

After V1 runs against real forward data, safe owner operations can be reviewed separately. Candidates are pause/freeze research and incident acknowledgement. Treasury approval, live-order control and signer actions remain separate security projects.
