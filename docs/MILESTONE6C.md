# Milestone 6C — Hyperliquid Funding-Carry Forward Runner

## Purpose

Milestone 6C is the first venue-specific unattended forward runner. It turns live public Hyperliquid market data into paper/shadow evidence for a frozen `ForwardStudy` using a long-spot / short-perpetual funding-carry strategy.

It does **not** trade a Hyperliquid account. The runner has no account address, API wallet, signing key, exchange-action client, transfer method, bridge method, or live order path.

## Frozen study configuration

A compatible study must have:

- `family = funding`
- `venue = hyperliquid`
- an immutable registered strategy version and experiment from Milestone 6B
- `study_config_json.runner = hyperliquid_carry_v1`

Supported frozen runner values:

```json
{
  "runner": "hyperliquid_carry_v1",
  "paired_notional_usd": "100",
  "horizon_hours": 24,
  "min_edge_bps": "10",
  "planned_loss_pct": "0.02",
  "spot_fee_bps": "7.0",
  "perp_fee_bps": "4.5",
  "slippage_reserve_bps_per_leg": "2",
  "shadow_delay_ms": 1000,
  "max_exit_delay_hours": 6,
  "max_funding_oracle_age_minutes": 5
}
```

`paired_notional_usd * 2` may not exceed the study's initial capital. This is only the first no-leverage guard. After executable entry books are simulated, the hardened worker recalculates the actual fully collateralized requirement from both executable notionals plus entry fees and compares it with current simulated flat equity (`initial capital + realised P&L`). If the actual requirement exceeds available simulated equity, the execution observation is retained but no open paper position is allowed.

`max_funding_oracle_age_minutes` is frozen with the study. A funding payment is not reconstructed when the latest persisted oracle observation at that funding timestamp is older than this limit.

## Entry process

For each active Hyperliquid funding study, the runner:

1. fetches/persists the current public perp and spot market state;
2. finds the study instrument and its USDC spot market (including BTC -> UBTC spot aliasing);
3. evaluates the pre-registered funding/cost rule;
4. rounds quantity down to the perp market size precision;
5. obtains current public L2 books for both legs;
6. simulates the paper spot buy and perp sell;
7. waits the frozen shadow delay;
8. obtains a second independent public L2 snapshot and simulates the same orders;
9. records paper-vs-shadow execution evidence for both legs;
10. requires all four paper/shadow leg simulations to be full fills;
11. recalculates actual fully collateralized capital from executable prices and fees;
12. opens the paper carry position only when that actual requirement fits inside current simulated equity.

A partial/rejected leg therefore contributes execution-quality evidence but cannot create a position. An otherwise executable entry that would imply hidden leverage is also rejected as a position while its execution observation remains in the forward dataset.

## Position accounting and risk exit

The position stores entry spot/perp mids, executable paper prices, entry fees and adverse slippage, quantity, actual allocated capital, a planned-loss amount, frozen target close time, and eventual exit/funding/P&L state.

`planned_loss_usd` is an enforced paper-risk limit, not descriptive metadata. On every holding cycle before the horizon, the hardened runner obtains current executable liquidation books for the long spot and short perp legs and computes the complete net liquidation result including accrued funding, fees, and adverse slippage. If that net result reaches or breaches the frozen planned-loss amount, the runner executes the normal paper+shadow exit workflow immediately with `close_reason = planned_loss`.

If full executable liquidation is unavailable while checking the planned-loss limit, the runner records an operational incident rather than pretending the limit was enforceable from midpoint prices.

Only one open position per study is permitted. Multiple-open-position state is treated as an operational error rather than silently aggregated.

## Funding accounting

Settled public funding history is refreshed while a position is open, not only at horizon close. After two hours of carry exposure, an empty settled-funding history is treated as a data-integrity failure rather than silently valued as zero funding.

Funding is reconstructed as:

`position_size * oracle_price * funding_rate`

For each settled funding timestamp, the runner uses the most recent persisted `oracle_px` at or before that timestamp. If no oracle snapshot exists, or if it is older than the study's frozen `max_funding_oracle_age_minutes`, valuation fails closed as data-integrity loss instead of substituting mark price or entry price.

Positive funding is credited to the short-perp position; negative funding is a cost.

## Gross, costs and net P&L

Gross strategy P&L is measured from midpoint movement plus settled funding:

- spot: `qty * (exit_spot_mid - entry_spot_mid)`
- short perp: `qty * (entry_perp_mid - exit_perp_mid)`
- plus settled funding

Execution costs are explicit:

- venue fees from simulated executable books;
- adverse entry/exit slippage relative to contemporaneous midpoint.

The journal enforces:

`net P&L = gross P&L - fees - slippage`

The closed trade and position-close state are written in one database commit, and the close reason is stored in both position state and trade metadata.

## NAV

The runner records the study's initial NAV and then at most one NAV mark per UTC hour.

When flat:

`NAV = initial capital + realised closed-trade P&L`

When a carry position is open, settled funding is refreshed before valuation and NAV is marked using a fully executable current paper liquidation of both legs plus accrued funding. If current depth cannot fully liquidate both sides, the runner does not invent a NAV value; it records an operational warning and lets the Milestone 6B NAV-gap gate expose persistent data/liquidity failures.

A NAV row is timestamped at the **actual observation / executable-book timestamp**. The UTC hour is used only to deduplicate sampling frequency. The runner never backdates a current observation to the beginning of the hour.

## Idempotency

Entry and exit attempts use deterministic hourly keys. A completed two-leg attempt cannot be duplicated in the same hour. Detecting only one persisted leg is an error instead of silently treating the partial write as a complete attempt.

The paper and delayed-shadow books for an attempt are collected before position persistence. A process crash during that capture therefore cannot leave a persisted position whose shadow observation is later fabricated from an unrelated delayed book.

## Deployment

The only supported unattended worker is:

```text
python -m app.workers.hyperliquid_forward_runner
```

That worker instantiates `HardenedHyperliquidCarryForwardRunner`.

Docker Compose places it behind the explicit `forward` profile:

```text
docker compose --profile forward up hyperliquid-forward-runner
```

The normal collectors/API do not start this worker automatically.

Default poll interval: five minutes (`HYPERLIQUID_FORWARD_POLL_SECONDS=300`).

## Safety boundary

Milestone 6C adds no:

- Hyperliquid user/account endpoint;
- API/agent wallet;
- private key or seed phrase;
- signer capability;
- exchange/order action endpoint;
- deposit/withdrawal/bridge capability;
- vault access;
- live-capital authorization;
- automatic promotion from `GREEN-1_CANDIDATE`.

Every market interaction is through Hyperliquid's public read-only `info`/book/funding data already used by the research collector.

## Next

After this runner is validated and deployed, it can begin accumulating genuine funding/carry forward observations. Polymarket and Solana should receive separate venue-specific runners later; they must not share state or contaminate the Hyperliquid study.
