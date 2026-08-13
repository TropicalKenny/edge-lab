# Dashboard V1 — Hosted Research Terminal

## Purpose

Dashboard V1 gives the owner a browser UI for Edge Lab while the research workers continue running on the VPS.

The UI is deliberately **read-only**. It displays forward-study NAV, evidence state, research P&L, trade/execution counts, incidents and recent closed paper trades. It cannot sign, submit venue orders, move funds, reach the owner vault, change strategy status, or authorize live capital.

All NAV/capital/P&L values in Dashboard V1 are **simulated research values**. Each frozen forward study has its own independent simulated bankroll. The overview may add those bankrolls together for observability, but that aggregate is not a real portfolio balance, is not money in the owner vault, and is not deployable capital. Live capital is explicitly reported as `$0` in this milestone.

## Hosted gateway routes

The Internet-facing process is `app.dashboard_server`, not the internal research API. It exposes only:

- `/` — redirect to `/dashboard`;
- `/dashboard` — responsive UI;
- `/dashboard/assets/dashboard.css` and `/dashboard/assets/dashboard.js` — repository-local assets;
- `/dashboard/api/summary` — read-only aggregate research data;
- `/healthz` — dashboard/database health.

Swagger, ReDoc and OpenAPI publication are disabled. Internal `/risk`, `/paper`, `/venues`, `/forward`, `/portfolio` and signer surfaces are not mounted in the hosted gateway.

## Production topology

```text
Owner browser
  -> Cloudflare Access
  -> Cloudflare Tunnel
  -> cloudflared container
       │ dashboard_gateway network only
       ▼
  dashboard:8080
       │ dashboard_gateway + private default network
       ▼
  edge_dashboard PostgreSQL login
       │ exact table allowlist, SELECT only
       ▼
  PostgreSQL

Private research network
  api:8000 / host loopback 127.0.0.1:8000
  collectors / forward runners / evaluator
  PostgreSQL / Redis
```

The dashboard is also bound to host loopback only at `127.0.0.1:8080` for VPS diagnostics.

**Cloudflared and the research API share no Docker network.** This is intentional. Even if a remotely managed Cloudflare Public Hostname is accidentally configured as `http://api:8000`, the cloudflared container cannot resolve/reach the research API service directly.

The correct Cloudflare origin is:

```text
http://dashboard:8080
```

Never target `http://api:8000`.

## Read-only database boundary

`deploy/compose.dashboard.yml` creates a separate PostgreSQL login named `edge_dashboard`. It is explicitly non-superuser, cannot create databases/roles, cannot bypass row security, and receives no write grants.

Before every dashboard start, the bootstrap removes any earlier broad table/default privileges and grants SELECT only to the exact table allowlist Dashboard V1 currently needs:

- `strategies`
- `strategy_versions`
- `strategy_evaluation_runs`
- `forward_studies`
- `forward_nav_observations`
- `forward_study_incidents`
- `forward_trade_records`
- `forward_execution_records`

It does **not** receive `SELECT ON ALL TABLES`, and it does not automatically inherit access to future tables. This prevents a later wallet, treasury or other sensitive table from becoming readable by the hosted dashboard merely because a migration creates it.

Runtime verification introspects PostgreSQL privileges and fails unless the dashboard's readable table set is exactly this allowlist and INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER are all unavailable.

Set a distinct `DASHBOARD_DB_PASSWORD` in `deploy/.env.forward`. Use a long random value and never commit the real environment file.

## Cloudflare setup order

1. Create a Cloudflare Zero Trust **Self-hosted** Access application for the intended dashboard hostname.
2. Use a deny-by-default owner-only Allow policy; do not use Allow Everyone.
3. Enable the identity-provider/MFA requirements you want for owner access.
4. Create a remotely managed Cloudflare Tunnel.
5. Configure its Public Hostname to the same hostname and set the service/origin URL to **`http://dashboard:8080`**.
6. Enable **Protect with Access** for the published application.
7. Put only the generated tunnel token in `deploy/.env.forward` as `CLOUDFLARE_TUNNEL_TOKEN`.
8. Run preflight, start the research stack, then start the tunnel:

```sh
sh deploy/preflight-forward.sh
sh deploy/start-forward.sh
sh deploy/start-dashboard-tunnel.sh
```

9. On the VPS, verify `http://127.0.0.1:8080/healthz` and `/dashboard` respond.
10. Open the public hostname externally and confirm Cloudflare Access authentication appears before Edge Lab.
11. Run:

```sh
sh deploy/verify-forward.sh --with-dashboard --strict
```

12. Verify ports 8000, 8080, PostgreSQL and Redis are not publicly reachable. The 8000/8080 host bindings are loopback only.

The hostname itself is intentionally not hard-coded in the repository.

## Browser hardening

The isolated gateway applies:

- same-origin Content Security Policy;
- frame blocking;
- MIME no-sniff;
- no-referrer policy;
- restrictive Permissions Policy;
- same-origin opener/resource policies;
- HSTS;
- no-index/no-archive robots policy;
- `Cache-Control: no-store`.

Its health endpoint fails when signing is enabled or its read-only database connection is unavailable.

## UI information architecture

### Overview

- aggregate **simulated** forward-study NAV;
- return across independent frozen study bankrolls;
- closed research P&L;
- worst observed drawdown among independent study NAV series;
- active study count;
- unresolved incidents and permanent data-integrity contamination;
- NAV history per study;
- strategy study cards;
- recent paper trades;
- explicit live-capital `$0`, signer/order/fund/vault safety state.

The aggregate simulated NAV is never presented as owner-vault balance or real portfolio NAV.

### Strategies

Each frozen study shows its version, family, venue, instrument, current simulated NAV, P&L, observed drawdown, elapsed forward days, trade count, shadow observations and latest evidence recommendation/reasons.

`GREEN-1_CANDIDATE` remains evidence only. The UI cannot promote a strategy.

### Trades

Closed records are normalized forward research journal entries. They are simulated/shadow evidence, not live fills.

### Incidents

Unresolved incidents are shown prominently. A study with **any** data-integrity incident remains contaminated even if the operational incident was later resolved, matching the frozen-evidence policy.

## Mobile behavior

The dashboard is light-first, supports an optional local dark theme, collapses navigation to a fixed bottom bar on phones, uses horizontal scrolling only for dense trade tables, and has no hover-only control dependency.

## Safety contract

The dashboard aggregate API reports a safety object equivalent to:

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

It also identifies capital scope as `independent-simulated-forward-study-bankrolls`.

Dashboard V1 adds no POST/PATCH/PUT/DELETE dashboard routes. The hosted gateway does not mount the private research API. Cloudflare hosting grants no access to wallet/private-key material, the owner vault, a venue signer or fund-transfer functions.

## Next UI milestone

After the hosted read-only dashboard is running against real forward data, safe owner operations such as pausing research or acknowledging incidents can be reviewed separately. Treasury approval, live-order controls and signer-related operations remain separate security projects.
