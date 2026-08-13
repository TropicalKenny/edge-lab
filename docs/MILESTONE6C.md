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
  "max_exit_delay_hours": 6
}
```

`paired_notional_usd * 2` may not exceed the study's initial capital. This preserves the V1 no-naked-leverage research boundary: one capital sleeve funds spot and another collateral sleeve backs the equal-size short-perp leg.

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
10. opens a paper carry position only when **all four** paper/shadow leg simulations are full fills.

A partial/rejected leg therefore contributes execution-quality evidence but cannot create a position.

## Position accounting

The position stores:

- entry spot/perp mids;
- entry executable paper prices;
- entry fees and adverse slippage;
- quantity and paired capital;
- frozen target close time;
- planned-loss amount used only as research/risk metadata;
- eventual exit prices/mids, funding, P&L and close reason.

Only one open position per study is expected. Multiple-open-position state is treated as an operational error rather than silently aggregated.

## Funding accounting

At close, the runner refreshes settled public funding history. Funding P&L for the short-perp leg is reconstructed from settled funding rates and the most recent persisted perp mark at each funding timestamp, falling back to the entry perp mid only when no earlier mark snapshot is available.

Positive Hyperliquid funding is credited to the short position; negative funding is a cost.

## Gross, costs and net P&L

Gross strategy P&L is measured from midpoint movement plus settled funding:

- spot: `qty * (exit_spot_mid - entry_spot_mid)`
- short perp: `qty * (entry_perp_mid - exit_perp_mid)`
- plus settled funding

Execution costs are then kept explicit for Milestone 6 cost stress:

- venue fees from the simulated executable books;
- adverse entry/exit slippage relative to the contemporaneous midpoint.

The journal enforces:

`net P&L = gross P&L - fees - slippage`

The closed trade and the position-close state are written atomically.

## NAV

The runner records the study's initial NAV and then at most one NAV mark per UTC hour.

When flat:

`NAV = initial capital + realised closed-trade P&L`

When a carry position is open, NAV is marked using a fully executable current paper liquidation of both legs plus accrued funding. If current depth cannot fully liquidate both sides, the runner does not invent a NAV value; it records an operational warning and lets the Milestone 6B NAV-gap gate expose persistent data/liquidity failures.

## Idempotency

Entry and exit attempts use deterministic hourly keys. A completed two-leg attempt cannot be duplicated in the same hour. Detecting only one persisted leg is an error instead of silently treating the partial write as a complete attempt.

## Deployment

The worker is:

```text
python -m app.workers.hyperliquid_forward_runner
```

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

After this runner is validated and deployed, we can begin accumulating genuine funding/carry forward observations. Polymarket and Solana will receive separate venue-specific runners later; they should not share state or silently contaminate the Hyperliquid study.
