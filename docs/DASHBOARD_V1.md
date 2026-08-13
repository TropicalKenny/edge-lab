# Dashboard V1 — Hosted Research Terminal

## Purpose

Dashboard V1 gives the owner a browser UI for Edge Lab while research workers continue running on the VPS.

The UI is deliberately **read-only**. It displays forward-study NAV, evidence state, research P&L, trade/execution counts, incidents and recent closed paper trades. It cannot sign, submit venue orders, move funds, reach the owner vault, change strategy status, or authorize live capital.

## Routes

- `/dashboard` — responsive dashboard page.
- `/dashboard/assets/dashboard.css` — local visual system.
- `/dashboard/assets/dashboard.js` — local read-only renderer.
- `/dashboard/api/summary` — aggregate read-only dashboard payload.

No third-party CDN or browser analytics dependency is required.

## Hosting model

The research API and the hosted dashboard are separate ASGI surfaces.

```text
Owner browser
  -> Cloudflare Access authentication
  -> Cloudflare Tunnel
  -> dashboard-only service: http://dashboard:8080
  -> edge_dashboard PostgreSQL role (SELECT-only)

VPS-only
  -> internal API: 127.0.0.1:8000
  -> PostgreSQL / Redis / workers: no public ports
```

`app.dashboard_server` mounts only Dashboard V1 plus `/healthz`. It does not mount signer, risk, venue refresh/scan, research-ingestion, portfolio mutation, treasury, or internal operations routes.

The dashboard receives a dedicated PostgreSQL login named `edge_dashboard`. The hosting bootstrap grants it CONNECT, schema USAGE and SELECT only, including default SELECT privileges for future tables. It never receives the main `edge` database credential.

The `cloudflared` container shares only the isolated `dashboard_edge` network with the dashboard service. Do not point the tunnel at `api:8000`.

## Cloudflare setup order — important

**Create the Cloudflare Access application before publishing the tunnel hostname.** The public hostname must never spend an interval exposed without the intended Access policy.

Recommended setup:

1. In Cloudflare Zero Trust, create a **Self-hosted** Access application for the dashboard hostname, for example `edge.example.com`.
2. Add an **owner-only Allow policy** restricted to the owner's identity/email or approved identity-provider group. Do not use Allow Everyone.
3. Require the identity-provider/MFA controls you want for owner access.
4. Create a remotely managed Cloudflare Tunnel for the Edge Lab VPS.
5. Publish the same hostname with origin URL **`http://dashboard:8080`**.
6. **Do not point the tunnel at `api:8000`.**
7. Enable **Protect with Access** for the published application when available so the tunnel validates the Access token before forwarding.
8. Copy only the generated Tunnel token into uncommitted `deploy/.env.forward` as `CLOUDFLARE_TUNNEL_TOKEN`.
9. Create a separate random `DASHBOARD_DB_PASSWORD` of at least 24 URL-safe characters. It must not equal `POSTGRES_PASSWORD`.
10. Start the private research stack, then the dashboard tunnel:

```sh
sh deploy/start-forward.sh
sh deploy/start-dashboard-tunnel.sh
```

11. Open `https://edge.example.com/dashboard` and confirm Cloudflare Access appears before Edge Lab.
12. Verify externally that PostgreSQL, Redis and port 8000 are not publicly reachable.

The hostname is intentionally not hard-coded in the repository. Domain changes belong in Cloudflare's control plane.

## Tunnel and database secret handling

`deploy/compose.dashboard-tunnel.yml` passes the remotely managed tunnel credential through `TUNNEL_TOKEN`; it is not placed on the `cloudflared` command line.

`deploy/start-dashboard-tunnel.sh` refuses to start when:

- `deploy/.env.forward` is missing;
- the tunnel token is empty or an obvious placeholder;
- `DASHBOARD_DB_PASSWORD` is missing, too short, unsafe for the connection URL, or equals the PostgreSQL admin password; or
- `SIGNER_ENABLED` is anything other than `false`.

The launcher always exports `SIGNER_ENABLED=false`.

## UI information architecture

### Overview

- combined forward-study NAV;
- return versus frozen starting capital;
- closed research P&L;
- active study count;
- unresolved/data-integrity incidents;
- NAV history;
- strategy study cards;
- recent paper trades;
- explicit signer/order/fund/vault safety state.

### Strategies

Each frozen study shows version, family, venue, instrument, current NAV, P&L, elapsed forward days, trade count, shadow observations and latest recommendation/reasons.

`GREEN-1_CANDIDATE` remains evidence only. The UI cannot promote a strategy.

### Trades

Closed records come from the normalized forward research journal. They are simulated/shadow evidence, not live fills.

### Incidents

Unresolved incidents are prominent. A study with any data-integrity incident remains contaminated even if an operational incident is later resolved.

## Mobile behavior

The dashboard is light-first, supports a local dark theme, collapses navigation to a fixed bottom bar on phones, uses horizontal scrolling only for dense tables, and has no hover-only dependency.

## Safety contract

The dashboard aggregate API reports:

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

The Cloudflare hosting layer changes only how the authenticated owner reaches the read-only surface. It grants neither Cloudflare nor the dashboard access to a wallet/private key, owner vault, venue signer, or fund-transfer function.

## Next UI milestone

After V1 runs against real forward data, safe owner operations can be added in a separate reviewed milestone. Candidates are pause/freeze research and incident acknowledgement. Treasury approval, live-order control and signer actions remain separate security projects.
