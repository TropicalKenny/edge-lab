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
  -> VPS loopback/private Edge Lab API
  -> /dashboard
```

PostgreSQL, Redis, research workers and future signer services must remain private. Do not expose database ports or worker containers to the public Internet.

The hardened forward deployment already binds the API to loopback. A Cloudflare Tunnel can therefore target the local dashboard/API service without opening the database or worker network.

## Authentication boundary

Dashboard V1 does not implement an application password. Production Internet access should be gated by Cloudflare Access before the request reaches Edge Lab. The first production deployment should use an allow policy restricted to the owner's identity.

Do not publish `/dashboard` directly on an unrestricted VPS port.

## UI information architecture

### Overview

- aggregate **simulated** forward-study NAV;
- return versus each independent frozen study's starting bankroll;
- closed research P&L;
- worst observed drawdown among the independent study NAV series;
- active study count;
- unresolved incidents and permanent data-integrity contamination;
- NAV history chart per study;
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

## Next UI milestone

After V1 runs against real forward data on the VPS, add safe owner operations in a separate reviewed milestone. Candidate controls are pause/freeze research and incident acknowledgement. Treasury approval, live-order control and any signer-related action remain separate security projects and are not implied by this dashboard.
