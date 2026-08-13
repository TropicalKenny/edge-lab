# Dashboard V1 — Hosted Research Terminal

## Purpose

Dashboard V1 gives the owner a browser UI for Edge Lab while research workers continue running on the VPS. It is deliberately **read-only** and cannot sign, submit venue orders, move funds, reach the owner vault, change strategy status, or authorize live capital.

## Routes

- `/dashboard`
- `/dashboard/assets/dashboard.css`
- `/dashboard/assets/dashboard.js`
- `/dashboard/api/summary`

No third-party CDN or browser analytics dependency is required.

## Hosting model

The internal research API and the Internet-facing dashboard are separate ASGI surfaces:

```text
Owner browser
  -> Cloudflare Access
  -> Cloudflare Tunnel
  -> http://dashboard:8080
  -> edge_dashboard PostgreSQL role (SELECT-only)

VPS-only
  -> internal API: 127.0.0.1:8000
  -> PostgreSQL / Redis / workers: no public ports
```

`app.dashboard_server` mounts only Dashboard V1 and `/healthz`; it does not mount signer, risk, venue scan/refresh, research-ingestion, portfolio mutation, treasury, or internal operations routes.

The dashboard gets a dedicated `edge_dashboard` PostgreSQL login with CONNECT, schema USAGE and SELECT only, including default SELECT privileges for future tables. It never receives the main `edge` database password.

`cloudflared` shares only the isolated `dashboard_edge` network with the dashboard. **Do not point the tunnel at `api:8000`.**

## Cloudflare setup order — important

**Create the Cloudflare Access application before publishing the tunnel hostname.**

1. Create a **Self-hosted** Access application for the dashboard hostname, e.g. `edge.example.com`.
2. Add an **owner-only Allow policy**. Do not use Allow Everyone.
3. Require the identity-provider/MFA controls you want.
4. Create a remotely managed Cloudflare Tunnel.
5. Publish the hostname with origin URL **`http://dashboard:8080`**.
6. Do not point the tunnel at `api:8000`.
7. Enable **Protect with Access** when available.
8. Put only the generated Tunnel token into uncommitted `deploy/.env.forward` as `CLOUDFLARE_TUNNEL_TOKEN`.
9. Set a separate random `DASHBOARD_DB_PASSWORD` of at least 24 URL-safe characters; it must differ from `POSTGRES_PASSWORD`.
10. Run preflight, start research, then start the tunnel:

```sh
sh deploy/preflight-forward.sh
sh deploy/start-forward.sh
sh deploy/start-dashboard-tunnel.sh
```

11. Verify runtime safety:

```sh
sh deploy/verify-forward.sh --with-dashboard --strict
```

12. Open `https://edge.example.com/dashboard` and confirm Access authentication appears before Edge Lab.

## Secret and runtime handling

`deploy/compose.dashboard-tunnel.yml` injects the tunnel token through `TUNNEL_TOKEN`; it is never appended to the `cloudflared` command line.

The deployment preflight rejects wallet/private-key material, unsafe signer state, placeholder secrets, weak/reused dashboard DB credentials, public PostgreSQL/Redis/dashboard ports, a non-loopback internal API, an incorrectly privileged dashboard DB URL, and a `cloudflared` service that can see internal credentials or networks beyond `dashboard_edge`.

The runtime verifier checks the exact Cloudflare-facing `dashboard` container, confirms its read-only safety flags, and confirms that `/signer/status` is not mounted there.

## UI information architecture

Dashboard V1 shows combined forward-study NAV, research P&L, active studies, incidents, NAV history, strategy evidence, recent paper/shadow trades and explicit signer/order/fund/vault safety state.

`GREEN-1_CANDIDATE` remains evidence only. The UI cannot promote a strategy.

## Mobile behavior

The dashboard is light-first, supports a local dark theme, uses a fixed bottom nav on phones, and avoids hover-only interactions.

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

Dashboard V1 adds no write routes under `/dashboard`. The hosting layer grants neither Cloudflare nor the dashboard access to a wallet/private key, owner vault, venue signer, or fund-transfer function.

## Next UI milestone

After V1 runs against real forward data, safe owner operations can be added separately. Candidates are pause/freeze research and incident acknowledgement. Treasury approval, live-order control and signer actions remain separate security projects.
