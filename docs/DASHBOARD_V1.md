# Dashboard V1 — Hosted Research Terminal

## Purpose

Dashboard V1 gives the owner a browser UI for Edge Lab while the research workers continue running on the VPS.

The UI is deliberately **read-only**. It displays forward-study NAV, evidence state, research P&L, trade/execution counts, incidents and recent closed paper trades. It cannot sign, submit venue orders, move funds, reach the owner vault, change strategy status, or authorize live capital.

## Routes

The hosted dashboard gateway exposes only:

- `/` — redirect to `/dashboard`.
- `/dashboard` — responsive dashboard page.
- `/dashboard/assets/dashboard.css` — local visual system.
- `/dashboard/assets/dashboard.js` — local read-only renderer.
- `/dashboard/api/summary` — aggregate read-only dashboard payload.
- `/healthz` — read-only gateway/database health probe.

The dashboard gateway disables Swagger, ReDoc and OpenAPI publication. It does **not** mount `/risk`, `/paper`, `/venues`, `/portfolio`, `/forward`, signer, or research-administration routes.

No third-party CDN or browser analytics dependency is required.

## Hosting model

The research API and the hosted dashboard are separate FastAPI processes built from the same codebase.

```text
Owner browser
  -> Cloudflare Access authentication
  -> Cloudflare Tunnel
  -> 127.0.0.1:8080  Edge Lab dashboard gateway
       -> SELECT-only PostgreSQL role

Private VPS only
  -> 127.0.0.1:8000  Edge Lab research API
  -> workers / collectors / evaluator
  -> PostgreSQL / Redis private Docker network
```

**Cloudflare Tunnel must target `http://127.0.0.1:8080`, never port 8000.**

The dashboard gateway runs `uvicorn app.dashboard_server:app --port 8080`. The internal research API remains bound to `127.0.0.1:8000`. PostgreSQL and Redis publish no host ports in the hardened forward deployment.

## Database boundary

The deployment creates an `edge_dashboard` PostgreSQL login for the dashboard process. It receives only:

- `CONNECT` on the `edge` database;
- `USAGE` on the `public` schema;
- `SELECT` on current tables;
- `SELECT` on future tables created by the `edge` owner through default privileges.

The dashboard process does not receive the research API's `edge` write credentials. A separate `DASHBOARD_DB_PASSWORD` is required in `deploy/.env.forward`.

## Authentication boundary

Dashboard V1 does not implement an application password. Production Internet access must be gated by Cloudflare Access before the request reaches Edge Lab. Use a deny-by-default Access policy that allows only the owner's identity.

Do not publish `/dashboard` directly on an unrestricted VPS port. Do not create a Cloudflare public hostname pointing at `127.0.0.1:8000`.

## Browser hardening

`app.dashboard_server` adds security headers including:

- strict same-origin Content Security Policy;
- `X-Content-Type-Options: nosniff`;
- `X-Frame-Options: DENY`;
- `Referrer-Policy: no-referrer`;
- camera/microphone/geolocation/payment/USB disabled through Permissions Policy;
- same-origin opener/resource policy;
- `Cache-Control: no-store`.

The dashboard health probe fails if `SIGNER_ENABLED` is true or if its read-only database connection is unavailable.

## UI information architecture

### Overview

- combined forward-study NAV;
- return versus each frozen study's starting capital;
- closed research P&L;
- active study count;
- unresolved and data-integrity incidents;
- NAV history chart;
- strategy study cards;
- recent paper trades;
- incident queue;
- explicit signer/order/fund/vault safety state.

### Strategies

Each frozen study shows its version, family, venue, instrument, current NAV, P&L, elapsed forward days, trade count, shadow observations and latest recommendation/reasons.

`GREEN-1_CANDIDATE` remains evidence only. The UI cannot promote a strategy.

### Trades

Closed records are from the normalized forward research journal. They are simulated/shadow evidence, not live fills.

### Incidents

Unresolved incidents are displayed prominently. A study with any data-integrity incident is displayed as contaminated even if an operational incident was later marked resolved, matching the frozen-evidence policy.

## Mobile behavior

The dashboard is light-first, supports an optional local dark theme, collapses navigation to a fixed bottom bar on phones, uses horizontal scrolling only for dense trade tables, and has no dependency on hover-only interactions.

## Safety contract

The dashboard aggregate API always reports:

```json
{
  "can_trade_live": false,
  "can_sign": false,
  "can_move_funds": false,
  "vault_accessible": false,
  "signer_enabled": false
}
```

Dashboard V1 adds no POST/PATCH/PUT/DELETE routes under `/dashboard`.

## VPS start

Copy `deploy/.env.forward.example` to `deploy/.env.forward` and set three distinct URL-safe secrets:

- `POSTGRES_PASSWORD`;
- `FORWARD_INGEST_SECRET`;
- `DASHBOARD_DB_PASSWORD`.

Then `deploy/start-forward.sh` starts both the private research API and the isolated dashboard gateway. The dashboard should be healthy at `http://127.0.0.1:8080/healthz` before a Cloudflare Tunnel is attached.

## Next UI milestone

After V1 runs against real forward data on the VPS, add safe owner operations in a separate reviewed milestone. Candidate controls are pause/freeze research and incident acknowledgement. Treasury approval, live-order control and any signer-related action remain separate security projects and are not implied by this dashboard.
