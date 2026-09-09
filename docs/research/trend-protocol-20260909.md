# M6N: locked Coinbase spot trend replay and forward signal observations

Registered 9 September 2026, before this implementation fetched any returns.
Machine-readable contract: `app/trend_protocol.json`; its SHA-256 is stored
with the immutable replay. No optimization loop or automatic promotion exists.

## Exact experiment

Actual Coinbase Exchange BTC-USD and ETH-USD public daily candles. No wrapped
BTC, perpetual, proxy venue or synthetic earlier history. Warmup starts
2019-01-01. Development: 2020-01-01 to 2023-01-01; validation: 2023-01-01 to
2025-01-01; final historical holdout: 2025-01-01 to 2026-09-01. Ends are
exclusive. All three windows are fixed before results. The historical holdout
is unseen by this implementation, not a claim nobody has seen these markets.
Each window starts with 1000 simulated USD, split equally into independent
BTC and ETH cash sleeves. No daily sleeve rebalancing, leverage, borrowing or
cash interest. Warmup cannot carry positions or profit into a window.

Primary 90-day simple moving average; one 180-day comparison. Close strictly
above the average means long, otherwise cash. Compare identical-cost
buy-and-hold and zero-interest cash. Costs per side: 60 bps taker fee and
5 bps adverse slippage. These are explicit scenarios, not verified owner
account fees. Actual venue fee tier must be checked before any execution
experiment. Quantity is cash divided by price including slippage and fee;
fees cannot create negative cash. Exits deduct both slippage and fees.

Daily OHLC cannot reproduce an execution at 00:05. For a candle dated D whose
close becomes available at D+1 midnight, replay fills at D+2 open: a full day
after the signal becomes knowable. Stress adds one more day. No trade fills
at the close that generated its signal. Last-window close liquidation is an
explicit terminal valuation convention, charged exit costs. It is not a
same-close strategy signal. Daily NAV includes hypothetical exit costs.

For every fixed window report base costs, doubled costs and one extra day of
delay for both moving averages and buy-and-hold. Report net return, dollar
P&L, drawdown, round trips and costs. Largest-winner removal subtracts the
largest profitable closed trade's dollar contribution; it does not resimulate
the subsequent capital path. No parameter is selected from holdout results.
Negative or benchmark-inferior results remain visible.

## Data integrity and runtime

The public candles endpoint limits requests to 300 buckets. Use 250-day
chunks, discard out-of-range provider extras, demand complete daily coverage,
validate OHLC/volume and fail on missing, duplicate, nonfinite or misaligned
bars. Never forward-fill market history. Persist the first valid raw candles
with capture times; conflicting refetched history fails. Cache validated
chunks across failures, then freeze the report and data hash after the first
complete replay. A changed protocol requires a separate versioned volume.

Daily forward **signal observations only**, first successful cycle after
00:05 UTC. Late starts carry actual observation timestamps. No backfilled
forward fills, positions or profit. Restart idempotency uses one record per
UTC date in transactional SQLite. There is no funded study, order client,
account API, wallet, signing or automatic strategy promotion.

Container `trend-research` uses named volume `edge-lab-trend-research-v1`.
SQLite WAL and FULL synchronous commits preserve protocol, raw history,
replay and observations. The local dashboard gets only a read-only mount
and adds a separate `trend_research` snapshot field. It is never summed into
the existing paper portfolio. Other snapshot readers without the mount
explicitly report unavailable. Summary writes use atomic replace; stale or
invalid summaries cannot report current readiness. Provider failures surface
as blocked and retry in five minutes, never as zero-profit success.

`deploy/start-dashboard-local.sh` starts this public-data worker alongside the
read-only dashboard; the typed `restart-dashboard-local` gateway deploys it.
Full deployment already calls that script. There are no new ports, credentials
or database grants. The named volume is **not covered by the existing PostgreSQL
backup job**; restoring this research store has not been verified. Do not remove
the volume on redeployment. Export/backup is a follow-up before relying on this
store as the only copy of long-running observations.

## Advancement

Review the frozen replay against cash, buy-and-hold, costs and drawdown before
adding a separately versioned executable-quote paper book. Observation alone
is not a profitability test. Forward fills need fresh bid/ask, spread/depth,
actual collection timestamps, restart-safe positions and missed-day handling.
No automatic simulated execution is implied by a positive replay.

The 14-day carry study and seven-day comparison remain the next independent
implementation milestone. Both old 72-hour validation paths must stay frozen;
new carry needs actual spot/perpetual identity, realized hourly funding and
full margin/reserve/basis/exit costs before it can be evaluated.

## Sources

- Coinbase public candle contract: https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles
- Public market data versus authenticated trading APIs: https://docs.cdp.coinbase.com/exchange/introduction/welcome
- Fee tiers depend on the account and order time: https://help.coinbase.com/coinbase/trading-and-funding/advanced-trade/advanced-trade-fees
