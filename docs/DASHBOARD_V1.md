# Dashboard V1 — VPS-Hosted Research Terminal

## Purpose

Dashboard V1 gives the owner a browser UI for Edge Lab while the research workers continue running on the shared OVH VPS.

The UI is deliberately **read-only**. It displays forward-study NAV, evidence state, research P&L, trade/execution counts, incidents and recent closed paper trades. It cannot sign, submit venue orders, move funds, reach an owner vault, change strategy status or authorize live capital.

All NAV/capital/P&L values are **simulated research values**. Live capital is explicitly `$0`.

## Hosting boundary

Edge Lab is hosted on the VPS. Cloudflare is only the public doorway.

```text
Owner browser
  -> Cloudflare-provided hostname / edge proxy
  -> private Cloudflare connectivity
  -> VPS loopback 127.0.0.1:8080
  -> app.dashboard_server
  -> edge_dashboard PostgreSQL role (exact-table SELECT-only)

Private Edge Lab services
  -> research API: 127.0.0.1:8000
  -> owner control API: 127.0.0.1:8090
  -> PostgreSQL / Redis / collectors / runners / evaluator
```

The shared-VPS port registry reserves `8000-8099` for Edge Lab. The browser dashboard target is **only** `127.0.0.1:8080`. Never route the public dashboard hostname to `8000` or `8090`.

`app.dashboard_server` mounts Dashboard V1, the owner login/OTP endpoints and `/healthz`. It does not mount signer, risk, paper simulation, venue, forward-operations, portfolio mutation or internal OpenAPI/documentation routes.

## Owner authentication

Authentication belongs to Edge Lab, not Cloudflare Access.

- Owner email: `fafikennedy20@gmail.com` by default.
- Login sends a six-digit one-time code through the configured transactional-email provider.
- Codes expire after 10 minutes by default, are single-use and have a bounded attempt count.
- Pending OTPs are stored only as HMAC digests in process memory; the plaintext code is not logged or persisted.
- Successful verification issues a signed `Secure`, `HttpOnly`, `SameSite=Lax` session cookie.
- The session signing secret is separate from database, Telegram, research-ingest and owner-control credentials.
- Unauthenticated dashboard/API requests fail closed or redirect to `/login`.

Required VPS-only secrets/settings:

```text
DASHBOARD_AUTH_SECRET
DASHBOARD_RESEND_API_KEY
DASHBOARD_AUTH_FROM_EMAIL
```

The real values live only in uncommitted VPS environment configuration.

## Database boundary

The hosted dashboard uses a separate PostgreSQL login named `edge_dashboard` with an exact-table **SELECT-only** policy.

Every dashboard bootstrap:

- makes the role non-superuser/non-creator/non-replication/non-bypass-RLS;
- defaults transactions to read-only;
- applies short statement/idle-transaction timeouts;
- removes broad/default table privileges;
- grants SELECT only to the explicit dashboard allowlist.

It does **not** receive `SELECT ON ALL TABLES`, and future tables do not automatically become visible. Authentication does not require or receive write access to the research database.

## Shared-VPS deployment rules

1. Check the shared VPS port registry before deployment.
2. Keep the dashboard published only as `127.0.0.1:8080:8080`.
3. Keep research API `8000` and owner-control API `8090` private.
4. Never bind an Edge Lab application port to `0.0.0.0`.
5. Cloudflare may proxy/tunnel to `8080`, but Cloudflare is not the Edge Lab runtime.
6. Do not reuse another project's reserved host range.
7. Verify active listeners and Docker published ports before restart.

Other currently reserved project ranges are maintained centrally in Aurent's `docs/VPS_PORT_REGISTRY.md`.

## Browser hardening

The dashboard adds same-origin CSP, frame blocking, MIME no-sniff, no-referrer policy, restrictive Permissions Policy, same-origin opener/resource policies, HSTS, no-index/no-archive and `Cache-Control: no-store`.

The health endpoint fails closed when signing is enabled or its database connection is unavailable. The public Cloudflare edge must not expose `/healthz` as a monitoring bypass.

## UI information architecture

### Overview

- aggregate **simulated** forward-study NAV;
- return across independent frozen study bankrolls;
- closed research P&L;
- worst observed drawdown;
- active study count;
- unresolved incidents and permanent data-integrity contamination;
- NAV history;
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

A study with **any** data-integrity incident remains contaminated even if that incident is later operationally resolved.

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

The hosting/authentication layer grants neither Cloudflare nor the dashboard access to a wallet/private key, owner vault, venue signer or fund-transfer function.

## Next control milestone

After the read-only dashboard is stable, browser control can be reviewed separately for a small typed allowlist such as pause/resume/freeze/lifecycle and incident acknowledgement. Those controls must call the private owner-control service; they must not expose arbitrary shell access, wallets, signing, live orders or fund movement.
