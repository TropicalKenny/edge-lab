# Milestone 6F — Polymarket Immediate Structural Forward Runner

## Purpose

M6F turns the public structural opportunities from M3 into genuine forward paper/shadow evidence. It still cannot trade Polymarket, sign, hold a wallet, bridge funds, or invoke CTF contracts.

The strategy version is pinned to the unchanged M3 analyzer commit `293321ef0d07cb79e317d33c4fe31aea4c724c8c` and the forward study freezes every execution assumption at bootstrap.

## Why the v1 universe is narrow

The runner accepts only structural baskets with an immediate deterministic collateral exit after all outcome tokens are acquired:

1. `binary_complete_set`
   - buy equal YES and NO shares in a standard non-NegRisk binary market;
   - a complete YES/NO pair can be merged back to one unit of collateral per share.

2. `negrisk_no_complete_set`
   - buy equal NO shares for every market in a complete non-augmented NegRisk event;
   - converting the complete NO set through the NegRisk adapter returns `(number_of_markets - 1) * quantity` collateral.

`negrisk_yes_complete_set` remains visible to the M3 research scanner but is deliberately excluded from M6F because its payoff is resolution-dependent rather than an immediate collateral conversion. Augmented NegRisk and dynamic `Other` outcomes remain fail-closed as in M3.

## Frozen configuration

The bootstrap creates a `family=other`, `venue=polymarket`, `instrument=STRUCTURAL_IMMEDIATE` study with runner `polymarket_structural_v1`.

Important frozen fields:

- discovery market/event caps;
- maximum shares;
- minimum edge;
- maximum book age;
- CLOB fee buffer;
- delayed shadow interval;
- fixed operation-cost reserve;
- planned-loss metadata percentage;
- repeat-attempt interval;
- maximum candidates attempted per cycle;
- the complete M6 evaluation policy.

Reusing the same study external ID with any changed frozen field is rejected instead of silently changing the experiment halfway through.

## Signal and delayed execution model

For each eligible candidate:

1. M3 discovery validates Gamma metadata against current CLOB market metadata.
2. Strict event completeness remains mandatory for NegRisk.
3. The M3 analyzer walks current ask depth and computes a fee-aware signal basket.
4. The signal must remain profitable after the frozen operation-cost reserve.
5. The runner waits the frozen shadow delay.
6. Every market is revalidated against current CLOB metadata.
7. The exact same intended quantity is walked against a second public book for every leg.
8. Partial depth, stale books, token/condition mismatch, or missing metadata produce execution evidence but no trade.
9. A closed forward trade is written only when every delayed leg is fully executable and the delayed basket still clears the frozen minimum edge after fees and operation cost.

The delayed book, not the optimistic signal book, determines the simulated trade P&L.

## Accounting

For a qualifying delayed basket:

- `gross P&L = deterministic collateral payout - delayed gross token cost`
- `fees = delayed CLOB fee estimate + frozen operation-cost reserve`
- `slippage = 0` in the trade journal because signal-to-delayed price movement is measured separately by M6 execution comparisons;
- `net P&L = gross P&L - fees`

The fixed operation-cost reserve is intentionally an assumption, not a claim about exact Polygon gas. It is visible in configuration, frozen at study creation, and the M6 evaluator additionally stress-multiplies observed costs.

`allocated_capital_usd` is the delayed basket cost plus fees and operation reserve. A candidate is skipped when this exceeds current simulated flat study equity. The runner never borrows or assumes leverage.

## Forward evidence integrity

- Signal and delayed book timestamps must fall inside the frozen forward-study period.
- More than one minute of future timestamp drift is treated as a permanent data-integrity failure.
- Any historical `data_integrity=true` incident permanently stops that study from making new Polymarket calls.
- An unresolved non-integrity critical incident pauses the study until resolved.
- Attempt keys are bucketed by structural identity and frozen retry interval so a persistent quote is not counted every poll.
- A database commit writes each completed attempt's delayed execution rows together; a trade row is linked only when the delayed basket actually qualifies.
- Flat NAV is recorded at most once per UTC hour from initial simulated capital plus realised forward trades.

## Deployment

The `forward` Compose profile now includes:

- `polymarket-forward-bootstrap` — one-shot frozen study creation;
- `polymarket-forward-runner` — public market-data loop;
- the existing public `polymarket-collector` for broad M3 forensic snapshots;
- the shared daily `forward-evaluator`.

The hardened VPS overlay passes the random PostgreSQL password to both Polymarket forward services and explicitly keeps `SIGNER_ENABLED=false`.

## Safety boundary

M6F adds no:

- private key or seed phrase;
- Polymarket account/funder address;
- L1/L2 authentication credentials;
- order creation/cancel endpoint;
- CTF merge/convert transaction call;
- relayer or bridge client;
- USDC transfer capability;
- live-capital authorization;
- strategy promotion.

Merge/convert mechanics are used only to calculate the deterministic paper payout. The code never invokes those on-chain operations.
