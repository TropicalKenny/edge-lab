# Dashboard V1 — Hosted Research Terminal

## Purpose

Dashboard V1 gives the owner a browser UI for Edge Lab while the research workers continue running on the VPS.

The UI is deliberately **read-only**. It displays forward-study NAV, evidence state, research P&L, trade/execution counts, incidents and recent closed paper trades. It cannot sign, submit venue orders, move funds, reach the owner vault, change strategy status, or authorize live capital.

All NAV/capital/P&L values in Dashboard V1 are **simulated research values**. Each frozen forward study has its own independent simulated bankroll. The overview may add those bankrolls together for observability, but that aggregate is not a real portfolio balance, is not money in the owner vault, and is not deployable capital. Live capital is explicitly reported as `$0` in this milestone.

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
  -> Cloudflare Access authentication
  -> Cloudflare Tunnel
  -> private Docker service: http://dashboard:8080
  -> edge_dashboard PostgreSQL role (SELECT-only)

VPS-only
  -> internal API: 127.0.0.1:8000
  -> PostgreSQL / Redis / research workers: no public ports
```

`app.dashboard_server` mounts only Dashboard V1 plus `/healthz`. It does not mount signer, risk, venue refresh/scan, research-ingestion, portfolio mutation, treasury, or internal operations routes.

The dashboard gets a dedicated PostgreSQL login named `edge_dashboard`, with CONNECT, schema USAGE and SELECT only, including default SELECT privileges for future tables. It never receives the main `edge` database password.

The `cloudflared` container shares only the isolated `dashboard_edge` network with the dashboard. **Do not point the tunnel at `api:8000`.**

## Cloudflare setup order — important

**Create the Cloudflare Access application before publishing the tunnel hostname.**

1. Create a Cloudflare Zero Trust **Self-hosted** Access application for the dashboard hostname, e.g. `edge.example.com`.
2. Add an **owner-only Allow policy**. Do not use Allow Everyone.
3. Require the desired identity-provider/MFA controls.
4. Create a remotely managed Cloudflare Tunnel.
5. Publish the hostname with origin URL **`http://dashboard:8080`**.
6. Do not point the tunnel at `api:8000`.
7. Enable **Protect with Access** when available.
8. Put only the generated Tunnel token into uncommitted `deploy/.env.forward` as `CLOUDFLARE_TUNNEL_TOKEN`.
9. `deploy/init-forward-env.sh` generates a separate random `DASHBOARD_DB_PASSWORD`; do not replace it with `POSTGRES_PASSWORD`.
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

The tunnel token is injected through `TUNNEL_TOKEN`, never appended to `cloudflared`'s command line.

Preflight rejects wallet/private-key material, unsafe signer state, placeholder secrets, reused/weak dashboard database credentials, public database/dashboard ports, a non-loopback internal API, a dashboard not using `edge_dashboard`, and a Cloudflare tunnel with internal credentials or networks beyond `dashboard_edge`.

Runtime verification tests the exact Cloudflare-facing `dashboard` container and confirms `/signer/status` is not mounted there.

## UI information architecture

### Overview

- aggregate **simulated** forward-study NAV;
- return versus each independent frozen study's starting bankroll;
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

The dashboard reports a safety object equivalent to:

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

It identifies capital scope as `independent-simulated-forward-study-bankrolls` and adds no write routes under `/dashboard`.

The hosting layer grants neither Cloudflare nor the dashboard access to a wallet/private key, owner vault, venue signer, or fund-transfer function.

## Next UI milestone

After V1 runs against real forward data, safe owner operations can be added separately. Candidates are pause/freeze research and incident acknowledgement. Treasury approval, live-order control and signer actions remain separate security projects.
