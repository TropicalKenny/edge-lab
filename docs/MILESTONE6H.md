# Milestone 6H — Private Hosted Forward Research Dashboard

Milestone 6H adds a private, read-only operational dashboard for the frozen forward-research studies created in M6C, M6F, and M6G.

It is an observability surface only. It does not add a live execution path or change any frozen research rule.

## Scope

The dashboard is served by the existing FastAPI process at:

- `GET /dashboard`
- `GET /dashboard/api/snapshot`

Both routes require separate dashboard credentials.

The page summarizes all three forward engines:

1. Hyperliquid funding carry
2. Polymarket immediate structural complete-set research
3. Solana Pump launch baseline

For each study it surfaces persisted operational state, NAV, forward age, trade/execution evidence counts, incidents, and the latest evaluation recommendation when one exists.

The dashboard also shows:

- aggregate simulated forward NAV and P&L
- ready / waiting / blocked study counts
- persisted NAV history for each venue
- recent forward-study incidents
- explicit safety state showing that live trading, signing, fund movement, and automatic strategy promotion are unavailable

## Source of truth

The browser does not reconstruct strategy performance or invent a second health model.

The server reuses the existing frozen operational status implementations:

- `ForwardOperationsService.study_statuses` for Hyperliquid
- `polymarket_forward_ops.study_statuses` for Polymarket
- `solana_forward_ops.study_statuses` for Solana

NAV history comes from `ForwardNavObservation`. Incidents come from `ForwardStudyIncident`. Evaluation recommendations come from the persisted `StrategyEvaluationRun` journal.

This keeps the dashboard downstream of the research journal rather than making the UI a new research engine.

## Authentication boundary

The dashboard uses its own credentials:

```text
DASHBOARD_USERNAME=
DASHBOARD_PASSWORD=
```

These credentials are deliberately separate from `FORWARD_INGEST_SECRET`.

The browser never receives the ingest secret, database credentials, provider API keys, wallet material, or signer material.

If either dashboard credential is unset, `/dashboard` fails closed with HTTP 503. Invalid or missing HTTP Basic credentials return HTTP 401.

HTTP Basic authentication must only be used behind HTTPS. Do not expose the dashboard over plaintext HTTP on the public Internet.

## Hosting boundary

The hardened forward Compose overlay continues to bind the API only to loopback:

```text
127.0.0.1:8000:8000
```

Do not change that to a public `0.0.0.0` host binding for production access.

Publish the dashboard through an authenticated HTTPS layer such as a private VPN, an HTTPS reverse proxy, or a private tunnel/access gateway. The proxy should forward only to the loopback FastAPI listener.

The application response also sends no-store caching, clickjacking protection, MIME sniffing protection, a restrictive referrer policy, and a Content Security Policy. The dashboard has no external JavaScript, font, chart, analytics, or CDN dependency.

## UI behavior

The dashboard is intentionally lightweight and dependency-free:

- server-rendered HTML shell
- same-origin JSON snapshot endpoint
- custom Canvas NAV chart
- responsive desktop/mobile layout
- manual refresh plus a 30-second read-only refresh interval

A temporary API or database failure is shown as a dashboard error. The UI does not convert missing evidence into a healthy state.

## Safety invariants

M6H must preserve all earlier safety boundaries:

- `SIGNER_ENABLED=false`
- no wallet or private key
- no venue order submission
- no Jupiter `/execute`
- no bridge or arbitrary token transfer
- no owner-vault access
- no live-capital authorization
- no automatic strategy-status promotion
- no dashboard POST/PUT/PATCH/DELETE route

The dashboard safety flags are all hard-coded false for live trading, signing, fund movement, and strategy promotion.

## VPS configuration

Add strong independent values to the uncommitted `deploy/.env.forward` file:

```text
DASHBOARD_USERNAME=<private username>
DASHBOARD_PASSWORD=<long random password>
```

Then restart/recreate only the API service through the existing hardened forward Compose stack so the new environment values are loaded.

The real `deploy/.env.forward` file remains uncommitted. The committed `deploy/.env.forward.example` contains placeholders only.

## Validation gate

M6H is mergeable only when CI passes:

- full repository pytest suite
- Python compilation
- fresh Alembic migration
- dashboard credentials fail closed when unset
- unauthorized and bad credentials are rejected
- authenticated page sends browser security/no-cache headers
- the snapshot endpoint never returns dashboard credentials
- the aggregate service consumes all three frozen status engines
- `/dashboard*` exposes GET only
- hardened VPS deployment remains loopback-only

No research engine or frozen experiment definition is modified by this milestone.
