# Milestone 6F — Polymarket Immediate Structural Forward Runner

## Purpose

M6F turns the public structural opportunities from M3 into genuine forward paper/shadow evidence. It still cannot trade Polymarket, sign, hold a wallet, bridge funds, or invoke CTF/NegRisk contracts.

The strategy version is pinned to the unchanged M3 analyzer commit `293321ef0d07cb79e317d33c4fe31aea4c724c8c` and the forward study freezes every execution assumption at bootstrap.

## Why the v1 universe is narrow

The runner accepts only structural baskets with an immediate deterministic collateral exit after all outcome tokens are acquired:

1. `binary_complete_set`
   - buy equal YES and NO shares in a standard non-NegRisk binary market;
   - merge the equal YES/NO pair back to one unit of collateral per share;
   - one structural action is reserved for operations-cost modeling.

2. `negrisk_no_complete_set`
   - buy equal NO shares for every market in a complete standard, non-augmented NegRisk event;
   - choose one NO leg and convert it into YES shares for every other event outcome;
   - pair those YES shares with the already-held NO shares in the remaining `N-1` markets and merge each pair;
   - the immediate deterministic collateral result is `(N-1) * quantity`;
   - the operational reserve therefore models `N` structural actions: one conversion plus `N-1` merges.

`negrisk_yes_complete_set` remains visible to the M3 research scanner but is deliberately excluded from M6F because its payoff is resolution-dependent rather than an immediate collateral conversion. Augmented NegRisk and dynamic `Other` outcomes remain fail-closed as in M3.

Reference mechanics are described by Polymarket's public documentation for standard merge operations and Negative Risk conversion. M6F models those mechanics only; it does not call them.

## Frozen configuration

The bootstrap creates a `family=other`, `venue=polymarket`, `instrument=STRUCTURAL_IMMEDIATE` study with runner `polymarket_structural_v1`.

Important frozen fields:

- discovery market/event caps;
- maximum shares;
- minimum edge;
- maximum book age;
- CLOB fee buffer;
- delayed shadow interval;
- per-structural-action operation-cost reserve;
- planned-loss metadata percentage;
- repeat-attempt interval;
- maximum candidates attempted per cycle;
- the complete M6 evaluation policy.

Reusing the same study external ID with any changed frozen field is rejected instead of silently changing the experiment halfway through. The initial NAV is also frozen to the study's configured simulated capital; a conflicting initial NAV blocks operations rather than being repaired silently.

## Signal and delayed execution model

For each eligible candidate:

1. M3 discovery validates Gamma metadata against current CLOB market metadata.
2. Strict event completeness is mandatory for NegRisk.
3. The M3 analyzer walks current ask depth and computes a fee-aware signal basket.
4. The signal must remain profitable after the frozen operation-cost reserve. For NegRisk NO baskets, the reserve scales with the conversion-plus-merge action count.
5. The runner waits the frozen shadow delay.
6. Standard binary markets are revalidated against current CLOB metadata.
7. NegRisk baskets additionally re-fetch the entire event after the delay. Event membership, condition IDs, token IDs, standard NegRisk status, non-augmented status, and absence of dynamic `Other` must still match the signal universe exactly.
8. The exact same intended quantity is walked against a second public book for every leg.
9. Partial depth, stale books, token/condition mismatch, changed NegRisk membership, unsafe event metadata, or missing metadata produce no simulated trade.
10. A closed forward trade is written only when every delayed leg is fully executable and the delayed basket still clears the frozen minimum edge after fees and operation reserve.

The delayed book, not the optimistic signal book, determines the simulated trade P&L.

## Accounting

For a qualifying delayed basket:

- `gross P&L = deterministic collateral payout - delayed gross token cost`
- `fees = delayed CLOB fee estimate + structural-action operation reserve`
- `slippage = 0` in the trade journal because signal-to-delayed price movement is measured separately by M6 execution comparisons;
- `net P&L = gross P&L - fees`

`POLYMARKET_FORWARD_OPERATION_COST_USD` is a frozen reserve **per structural action**, not a claim about exact Polygon gas or relayer pricing. A standard binary basket reserves one action. A standard NegRisk NO basket with `N` outcome markets reserves `N` actions. The M6 evaluator independently stress-multiplies observed costs as part of the evidence gate.

`allocated_capital_usd` is the delayed basket cost plus delayed CLOB fees and the full action-scaled operation reserve. A candidate is skipped when this exceeds current simulated flat study equity. The runner never borrows or assumes leverage.

## Forward evidence integrity

- Signal and delayed book timestamps must fall inside the frozen forward-study period.
- More than one minute of future timestamp drift is treated as a permanent data-integrity failure.
- Any historical `data_integrity=true` incident permanently stops that study before any new Polymarket market call.
- An unresolved non-integrity critical incident pauses the study until resolved.
- Attempt keys are bucketed by structural identity and frozen retry interval so a persistent quote is not counted every poll.
- Partial delayed fills remain execution evidence but never become profit-bearing trade rows.
- Flat NAV is recorded at most once per UTC hour from initial simulated capital plus realised forward trades.
- The initial NAV value/source is verified at bootstrap and by the read-only status command.

## Read-only status and health

Use:

```text
python -m app.polymarket_forward_ops status
```

For the default frozen study:

```text
python -m app.polymarket_forward_ops status \
  --external-id polymarket-structural-m6f-v1 \
  --require-ready --quiet
```

Readiness checks only database evidence and frozen lineage/configuration. It does not authenticate to Polymarket.

Operational states:

- `ready`: active frozen study, valid lineage/config/policy, correct initial NAV, no integrity/critical block, and fresh runner NAV heartbeat;
- `waiting`: structurally valid but the latest NAV heartbeat is older than `POLYMARKET_FORWARD_HEALTH_MAX_NAV_AGE_SECONDS` (default 7200 seconds);
- `blocked`: inactive/malformed lineage, permanent integrity contamination, unresolved critical incident, missing or conflicting initial NAV, or no NAV evidence.

Docker uses this command as the `polymarket-forward-runner` healthcheck.

## Deployment

The `forward` Compose profile includes:

- `polymarket-forward-bootstrap` — one-shot frozen study creation;
- `polymarket-forward-runner` — public market-data paper/shadow loop;
- the existing public `polymarket-collector` for broad M3 forensic snapshots;
- the shared daily `forward-evaluator`.

The hardened VPS overlay passes the random PostgreSQL password to both Polymarket forward services and explicitly keeps `SIGNER_ENABLED=false`.

Each venue runner depends only on its own successful bootstrap. The shared evaluator depends on database migration rather than on every venue bootstrap, so a Polymarket bootstrap failure cannot suppress Hyperliquid evaluation and vice versa.

## Safety boundary

M6F adds no:

- private key or seed phrase;
- Polymarket account/funder address;
- L1/L2 authentication credentials;
- order creation/cancel endpoint;
- CTF merge/convert transaction call;
- relayer or bridge client;
- collateral transfer capability;
- live-capital authorization;
- strategy promotion.

Merge/convert mechanics are used only to calculate deterministic paper payout and operation count. The code never invokes those on-chain operations.
