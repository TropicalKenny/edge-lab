# Dashboard V1 — Hosted Research Terminal

## Purpose

Dashboard V1 gives the owner a browser UI for Edge Lab while the research workers continue running on the VPS.

The UI is deliberately **read-only**. It displays forward-study NAV, evidence state, research P&L, trade/execution counts, incidents and recent closed paper trades. It cannot sign, submit venue orders, move funds, reach the owner vault, change strategy status, or authorize live capital.

All NAV/capital/P&L values in Dashboard V1 are **simulated research values**. Each frozen forward study has its own independent simulated bankroll. The overview may add those bankrolls together for observability, but that aggregate is not a real portfolio balance, is not money in the owner vault, and is not deployable capital. Live capital is explicitly reported as `$0` in this milestone.

## Routes

- `/dashboard` — responsive dashboard page.
- `/dashboard/assets/dashboard.css` — local visual system.
- `/dashboard/assets/dashboard.js` — local read-only renderer.
- `/dashboard/api/summary` — aggregate read-only dashboard payload.

No third-party CDN or browser analytics dependency is required.

## Hosting model

The FastAPI application remains on the VPS. The dashboard is served by the same application process, so there is no separate frontend server or Node runtime in V1.

Recommended exposure path:

```text
Owner browser
  -> Cloudflare Access authentication
  -> Cloudflare Tunnel
  -> private Docker service: http://api:8000
  -> /dashboard
```

PostgreSQL, Redis, research workers and future signer services remain private. The hardened forward overlay publishes the API to the VPS host only at `127.0.0.1:8000`; PostgreSQL and Redis publish no host ports. The `cloudflared` container reaches the API over the private Docker Compose network and itself publishes no host port.

This means the VPS does not need a public inbound dashboard port. The browser-facing hostname terminates at Cloudflare and the tunnel is outbound from the VPS.

## Cloudflare setup order — important

**Create the Cloudflare Access application before publishing the tunnel hostname.** The public hostname must not spend an interval exposed without the intended Access policy.

A recommended production setup is:

1. In Cloudflare Zero Trust, create a **Self-hosted** Access application for the intended dashboard hostname, for example `edge.example.com`.
2. Add an **Allow** policy restricted to the owner's identity/email or approved identity-provider group. Do not use an Allow Everyone policy.
3. Enable the identity-provider/MFA requirements you want for owner access.
4. Create a remotely managed Cloudflare Tunnel for the Edge Lab VPS.
5. In the tunnel's Published Application/Public Hostname configuration, publish the same hostname and set its service/origin URL to **`http://api:8000`**. This works because `cloudflared` and `api` share the private Docker Compose network.
6. Enable Cloudflare's **Protect with Access** option for the published application so the tunnel validates the Access token before forwarding the request.
7. Copy only the generated **Tunnel token** to `deploy/.env.forward` as `CLOUDFLARE_TUNNEL_TOKEN`. The token is a secret. Never commit the real `.env.forward` file.
8. Start the research stack, then start the tunnel:

```sh
sh deploy/start-forward.sh
sh deploy/start-dashboard-tunnel.sh
```

9. Open `https://edge.example.com/dashboard` and confirm Cloudflare Access authentication appears before Edge Lab.
10. From outside the VPS, verify that PostgreSQL, Redis and port 8000 are not publicly reachable. The host-side Edge Lab API should remain loopback-only.

The hostname is intentionally **not hard-coded in the repository**. Changing domains later should be a Cloudflare control-plane change, not an application rebuild.

## Tunnel token handling

`deploy/compose.dashboard-tunnel.yml` injects the remotely managed tunnel credential through the `TUNNEL_TOKEN` environment variable. The token is not appended to the process command and the tunnel container has no host port mapping.

`deploy/start-dashboard-tunnel.sh` refuses to start when:

- `deploy/.env.forward` is missing;
- `CLOUDFLARE_TUNNEL_TOKEN` is empty;
- the token contains an obvious example placeholder; or
- `SIGNER_ENABLED` is anything other than `false`.

The launcher always exports `SIGNER_ENABLED=false` before starting the tunnel service.

## Authentication boundary

Dashboard V1 does not implement an application password. Production Internet access is gated by Cloudflare Access before the request reaches Edge Lab. The first deployment should use an owner-only Allow policy.

Do not publish `/dashboard` directly on an unrestricted VPS port. Do not configure the tunnel hostname without the Access application/policy in place.

## UI information architecture

### Overview

- aggregate **simulated** forward-study NAV;
- return versus each independent frozen study's starting bankroll;
- closed research P&L;
- worst observed drawdown among the independent study NAV series;
- active study count;
- unresolved incidents and permanent data-integrity contamination;
- NAV history chart per independent study;
- strategy study cards;
- recent paper trades;
- incident queue;
- explicit live-capital `$0`, signer/order/fund/vault safety state.

The aggregate simulated NAV is never presented as owner-vault balance or real portfolio NAV.

### Strategies

Each frozen study shows its version, family, venue, instrument, current simulated NAV, P&L, observed drawdown, elapsed forward days, trade count, shadow observations and latest recommendation/reasons.

`GREEN-1_CANDIDATE` remains evidence only. The UI cannot promote a strategy.

### Trades

Closed records are from the normalized forward research journal. They are simulated/shadow evidence, not live fills.

### Incidents

Unresolved incidents are displayed prominently. A study with **any** data-integrity incident is displayed as contaminated even if that operational incident was later marked resolved, matching the frozen-evidence policy. The aggregate API therefore exposes permanent integrity counts separately from unresolved operational incidents.

## Mobile behavior

The dashboard is light-first, supports an optional local dark theme, collapses navigation to a fixed bottom bar on phones, uses horizontal scrolling only for dense trade tables, and has no dependency on hover-only interactions.

## Safety contract

The dashboard aggregate API always reports a safety object equivalent to:

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

It also identifies the capital scope as `independent-simulated-forward-study-bankrolls`.

Dashboard V1 adds no POST/PATCH/PUT/DELETE routes under `/dashboard`.

The Cloudflare hosting layer changes only how an authenticated owner reaches that read-only interface. It does not grant the dashboard, `cloudflared`, or Cloudflare access to a wallet/private key, the owner vault, a venue signer, or a fund-transfer function.

## Next UI milestone

After V1 runs against real forward data on the VPS, add safe owner operations in a separate reviewed milestone. Candidate controls are pause/freeze research and incident acknowledgement. Treasury approval, live-order control and any signer-related action remain separate security projects and are not implied by this dashboard.
