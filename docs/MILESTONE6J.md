# Milestone 6J — Research Acceleration

M6J increases **research throughput** without weakening Edge Lab's live-capital safety boundary.

## Invariants

M6J is observation-only. It does not create a wallet, signer, vault, transaction sender, order-submission client, swap path, bridge path, withdrawal path, transfer path, or live-capital path.

These invariants remain mandatory:

- `SIGNER_ENABLED=false`
- `can_trade_live=false`
- `can_sign=false`
- `can_move_funds=false`
- `wallet_access=false`
- `live_capital_usd=0`

M6J does **not** change the frozen M6C, M6F or M6G study configuration. It does not write `ForwardTradeRecord`, `ForwardExecutionRecord`, NAV, evaluation or promotion evidence. It writes only durable `ForwardScanObservation` telemetry under `research_lane=m6j`.

Baseline scan telemetry and M6J telemetry are reported separately. The dashboard/research snapshot excludes the M6J lane from baseline activity counts and exposes M6J as `research_acceleration`.

## Hyperliquid

The existing M6C BTC carry study remains the frozen control. M6J observes a broader carry surface:

- assets: BTC, ETH, SOL by default;
- horizons: 24h, 7d, 14d and 30d by default;
- current funding projection;
- trailing 7-day and 30-day mean funding projection;
- basis;
- the same conservative taker-fee/slippage cost model used by the control;
- positive-edge vs non-positive-edge counts.

The worker fetches only public market/funding data. It never opens a position.

## Polymarket

The M6F REST polling study remains the frozen control. M6J builds a public-data WebSocket research lane:

1. Discover and CLOB-validate up to 200 binary markets by default.
2. Load relevant NegRisk events.
3. Seed order books from the public CLOB API.
4. Subscribe to the public market WebSocket.
5. Re-run binary complete-set and NegRisk structural calculations on book events.
6. Persist only bounded edge telemetry: kind, ROI, notional, quantity, condition/event IDs and whether the frozen 10-bps baseline threshold would have qualified.

No authenticated Polymarket client is constructed.

## Solana

M6G remains the frozen safety/exitability baseline. M6J changes only the *research interpretation* of incomplete security data.

Candidates are classified:

- `SAFE`: all observed checks explicitly clean;
- `UNSAFE`: a confirmed dangerous fact is present, such as active mint/freeze authority, confirmed malicious creator, non-transferable token or non-zero transfer fee;
- `UNKNOWN`: required security evidence is missing or inconclusive.

`UNKNOWN` is not treated as `SAFE`. It is only eligible for a **counterfactual Jupiter quote observation** so Edge Lab can measure the opportunity cost of its filters.

Confirmed `UNSAFE` candidates are not quoted by M6J.

For `SAFE` and `UNKNOWN` candidates, M6J records:

- a quote-only hypothetical USDC entry;
- an immediate quote-only exit when available;
- quote-only outcome marks at 5/15/30/60 minutes by default;
- counterfactual P&L/return;
- the original tri-state classification and reasons.

Jupiter transaction material is never persisted. `compact_jupiter_quote()` has an explicit bounded allowlist and records only quote metadata plus whether transaction material was present.

## Deployment

M6J runs in three dedicated containers from `deploy/compose.m6j.yml` under the `research-acceleration` profile:

- `m6j-hyperliquid-research`
- `m6j-polymarket-research`
- `m6j-solana-research`

`deploy/start-forward.sh` starts them with the existing research stack. All three receive `SIGNER_ENABLED=false`; none publishes a port.

## Validation

Repository validation must include:

```bash
sh scripts/verify-repo.sh
```

This runs pytest, Python compilation, shell syntax, a fresh Alembic migration and Docker Compose rendering when Docker is available.

After deployment, verify:

```bash
python -m app.research_snapshot
```

The output should show baseline `activity` separately from `research_acceleration` and retain all live-trading safety flags as false/zero.

## What M6J does not do

M6J does not relax promotion criteria and does not authorize micro-live trading. Any future change from paper/shadow research to live capital remains a separate milestone requiring an explicit security review and owner authorization.
