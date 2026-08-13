# Dashboard V1 — Hosted Research Terminal

## Purpose

Dashboard V1 gives the owner a browser UI for Edge Lab while the research workers continue running on the VPS. The UI is deliberately **read-only**: it displays forward-study NAV, evidence state, research P&L, trades and incidents, but cannot sign, submit orders, move funds, reach the owner vault, change strategy status, or authorize live capital.

## Hosted gateway routes

The Internet-facing dashboard process is `app.dashboard_server`, not the internal research API. It exposes only:

- `/` — redirect to `/dashboard`;
- `/dashboard` — responsive UI;
- `/dashboard/assets/dashboard.css` and `/dashboard/assets/dashboard.js` — repository-local assets;
- `/dashboard/api/summary` — read-only aggregate data;
- `/healthz` — dashboard/database health.

Swagger, ReDoc and OpenAPI publication are disabled. Internal `/risk`, `/paper`, `/venues`, `/forward`, `/portfolio` and signer surfaces are not mounted in the hosted gateway.

## Production topology

```text
Owner browser
  -> Cloudflare Access
  -> Cloudflare Tunnel (cloudflared container)
  -> http://dashboard:8080
  -> Edge Lab dashboard-only FastAPI process
  -> PostgreSQL edge_dashboard role (SELECT only)

Private VPS services
  -> api:8000 / 127.0.0.1:8000
  -> collectors / research workers / evaluator
  -> PostgreSQL + Redis private Docker network
```

**The Cloudflare Public Hostname service/origin must be `http://dashboard:8080`. Never target `http://api:8000`.**

For local VPS diagnostics the dashboard is also bound only to `127.0.0.1:8080`. The hardened research API remains bound only to `127.0.0.1:8000`.

## Read-only database boundary

`deploy/compose.dashboard.yml` creates a separate `edge_dashboard` PostgreSQL login. It receives `CONNECT`, schema `USAGE`, and `SELECT` on current/future tables. It receives no INSERT, UPDATE or DELETE grant. The dashboard process therefore does not use the research API's write-capable `edge` login.

Set a distinct `DASHBOARD_DB_PASSWORD` in `deploy/.env.forward`. Use a long URL-safe random value and never commit the real file.

## Cloudflare setup order

1. Create a Cloudflare Zero Trust **Self-hosted** Access application for the intended hostname.
2. Use a deny-by-default policy that allows only the owner's identity or approved identity-provider group; do not use Allow Everyone.
3. Create the remotely managed Cloudflare Tunnel.
4. Configure its Public Hostname to the same hostname and set the service URL to **`http://dashboard:8080`**.
5. Enable Protect with Access for that published application.
6. Put only the generated tunnel token in `deploy/.env.forward` as `CLOUDFLARE_TUNNEL_TOKEN`.
7. Start the stack and tunnel:

```sh
sh deploy/start-forward.sh
sh deploy/start-dashboard-tunnel.sh
```

8. Verify `http://127.0.0.1:8080/healthz` is healthy on the VPS.
9. Open the public hostname and confirm Cloudflare authentication appears before Edge Lab.
10. Verify ports 8000, PostgreSQL and Redis are not publicly reachable.

The hostname itself is intentionally not hard-coded in the repository.

## Browser hardening

The isolated gateway applies a same-origin Content Security Policy, frame blocking, no-sniff, no-referrer, restrictive Permissions Policy, same-origin opener/resource policy and `Cache-Control: no-store`. Its health endpoint fails when signing is enabled or its read-only database connection is unavailable.

## UI information architecture

The UI remains the tested Dashboard V1 experience: combined NAV and return, research P&L, study/evidence cards and 90-day progress, NAV history, recent paper trades, unresolved incidents and explicit signer/order/fund/vault safety state. On mobile it uses bottom navigation and remains touch-first; desktop keeps the sidebar layout.

`GREEN-1_CANDIDATE` remains evidence only. The UI cannot promote a strategy.

## Safety contract

The aggregate payload reports:

```json
{
  "can_trade_live": false,
  "can_sign": false,
  "can_move_funds": false,
  "vault_accessible": false,
  "signer_enabled": false
}
```

No POST/PATCH/PUT/DELETE dashboard route, private key, wallet, bridge, transfer function or live-capital authorization is added by this deployment.

## Next UI milestone

After the hosted read-only dashboard is running against real forward data, safe owner operations such as pausing research or acknowledging incidents can be reviewed separately. Treasury approval, live-order controls and signer-related operations remain separate security projects.
