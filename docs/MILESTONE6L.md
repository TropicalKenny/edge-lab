# Edge Lab — Milestone 6L: Active Paper Strategy Experiments

Status: implementation branch `feature/m6l-active-paper-strategies`; paper/shadow only; no live execution authorization.

## Operating principle

M6L corrects an important research-design problem discovered during M6J/M6K: paper trading had inherited filters that were appropriate for eventual capital protection but so strict that several lanes generated almost no actual simulated trades.

The M6L principle is:

> **Paper mode optimizes for learning. Live mode optimizes for capital preservation.**

Paper experiments must still use realistic executable prices, delayed shadow observations, fees/slippage and explicit no-route losses. But an UNKNOWN safety field is not automatically a reason to suppress a paper experiment. Known mechanical impossibilities and known unsafe conditions remain hard blocks.

M6L does **not** enable any wallet, signer, private key, order submission, Jupiter `/execute`, transfer, bridge or real capital.

## Evidence that motivated M6L

A fresh VPS diagnostic on 5 September 2026 found:

- 20,851 Solana forensic feature snapshots in the recent research corpus;
- 520 forward outcome labels;
- naive 30-minute candidate outcomes were strongly negatively skewed, confirming that indiscriminate launch buying is not a strategy;
- current Solana M6G rejected essentially every launch before the alpha question could be tested;
- the existing feature pipeline already captures decision-time buy/sell flow (`momentum_score`), short-window sell ratio, volume acceleration, price change, market cap and executable Jupiter exit quality;
- early DEX liquidity and holder-concentration fields are currently too sparse/degenerate to be mandatory alpha inputs and therefore are not used as hard M6L-v1 entry requirements;
- M6K-HL's only distinct recent persistence pass was BTC/720h, with a modest mean 30-day realized carry edge. It is useful evidence but not a high-frequency P&L engine by itself;
- M6K-PM remains limited primarily by synchronized fresh-book availability rather than by a shortage of theoretical event relationships.

External research reviewed before freezing M6L-v1 also supports short-horizon, flow-aware Solana research, strong execution-friction accounting, profit-concentration stress tests, and synchronized executable depth for Polymarket rather than screen-price arbitrage.

## M6L-SOL — Meme Momentum Paper Strategy

M6G remains frozen as the safety/exitability control. M6L-SOL is a separate strategy lineage and separate forward studies.

### Two cohorts

Both cohorts use the same alpha and execution rules.

**strict**

- requires conclusive clean authority/security fields;
- blocks UNKNOWN safety state;
- useful as the capital-protection comparison cohort.

**exploratory**

- allows UNKNOWN decision-time security fields;
- still blocks known active mint/freeze authority, known non-transferability, known malicious creator and known non-zero transfer fees;
- records the exact UNKNOWN reasons with every candidate/trade;
- exists to measure the opportunity cost and failure rate of uncertainty rather than pretending UNKNOWN is SAFE.

### Entry universe

- chain-native Pump/PumpSwap launches already collected by Edge Lab;
- decision window: 3 to 20 minutes after observed launch;
- launches are re-evaluated inside that window until a real paper entry attempt occurs; an early missing enrichment snapshot does not permanently eliminate the launch;
- no hindsight data may alter an earlier decision.

### Alpha v1

The first challenger is intentionally deterministic and simple. It is not claimed to be historically optimized.

A candidate must have enough decision-time flow evidence and satisfy:

- `momentum_score >= 0.10` (net early buy pressure);
- `volume_acceleration >= 1.20` when the field is available;
- `sell_ratio_5m <= 0.55` when the field is available;
- no observed 5-minute collapse <= -20% when that field is available;
- no observed extreme +150% short-window spike when that field is available (manipulation/chase guard);
- at least three alpha-quality points under the stored v1 score.

The score is stored with its component values for later rejection/counterfactual review.

`liquidity_usd` and `top10_holder_pct` are **not** hard v1 alpha gates because current collected early-token distributions show those fields are not sufficiently informative/reliable in the present representation. They remain recorded for future feature-quality work.

### Execution realism

A signal does not become a simulated position unless Edge Lab can obtain:

1. Jupiter quote-only USDC -> token paper quote;
2. delayed shadow quote;
3. immediate token -> USDC preflight quote for the acquired amount.

Default paper assumptions:

- $25 simulated entry;
- 1-second paper-to-shadow delay;
- maximum quote impact 8%;
- minimum immediate exit recovery 88%;
- up to 10 concurrent positions;
- up to 5 new entries per cycle.

The M6G control remains at its own frozen stricter values.

### Exit v1

Meme positions are monitored against **executable Jupiter exit value**, not displayed chart price.

Each cycle records an executable recovery mark where available. M6L-v1 closes on the first of:

- hard stop: recovery <= 75% of entry;
- trailing reversal: after executable recovery reaches >=130%, close after a 15% retreat from the best executable mark;
- tighter trailing reversal: after recovery reaches >=175%, close after a 10% retreat from the best executable mark;
- maximum hold: 30 minutes;
- no executable route through the configured grace deadline: forced zero recovery.

There is deliberately no small fixed take-profit. The strategy must preserve the possibility of rare large winners while still measuring reversal risk.

### Evaluation additions

In addition to standard M6 evaluation, M6L reviews:

- daily net P&L;
- win/loss distribution;
- forced no-route loss rate;
- strict vs exploratory cohort difference;
- UNKNOWN-reason performance;
- entry/exit quote deterioration;
- profit concentration;
- P&L after removing the top 1, top 3 and top 5 winners;
- time-of-day and market-regime breakdowns;
- trade frequency and idle time.

A high cumulative return that disappears when a few outliers are removed is treated as fragile, not as proven edge.

## M6L-HL — Active carry challengers

M6K-HL remains the persistence research lane. M6L does not pretend the current BTC/720h persistence screen is a daily-return strategy.

The next Hyperliquid paper layer should:

- keep M6C frozen;
- continue cross-sectional M6K screening;
- register paper challengers only as separate strategy/study lineages;
- prefer real observed funding, executable spot/perp books and delayed shadow fills;
- measure capital efficiency explicitly;
- treat long-horizon BTC carry as a lower-frequency diversifier unless shorter-horizon/cross-sectional forward evidence improves.

The M6L-SOL implementation is prioritized first because it can generate much more independent learning per day.

## M6L-PM — Synchronized executable event research

M6F remains frozen. M6K-PM demonstrated that complete event relationships can be found but synchronized fresh books are the binding constraint.

The next Polymarket paper implementation should use batched `/books` snapshots for all legs of one explicit event where possible, record timestamp spread across legs, common executable depth and current fee schedules, then create paper trades only from a state that was executable together. Research priority is live-event/sports combinatorial relationships where current evidence suggests opportunities are more frequent but still small and liquidity-constrained.

No random trade is created merely to increase the trade counter.

## Economic target

The owner would ultimately like the system to become capable of approximately $20–$50/day and compound the capital base. M6L treats this as an **economic target to test**, not a promised return.

Every paper strategy should report:

- net return on simulated capital;
- average daily P&L;
- capital required to imply $20/day and $50/day at the measured forward return/risk profile;
- drawdown and tail losses at those scaled capital levels.

This prevents a strategy with a statistically real but economically tiny edge from being mistaken for the primary P&L engine.

## Safety boundary

M6L adds no:

- wallet or seed phrase;
- private key;
- signer;
- Jupiter taker or `/execute` call;
- Solana transaction submission;
- Hyperliquid order submission;
- Polymarket order submission;
- transfer, withdrawal or bridge action;
- live capital.

`SIGNER_ENABLED=false` remains mandatory.

## Initial implementation order

1. deploy M6L-SOL strict + exploratory paper/shadow cohorts;
2. verify that actual entries/exits/trades are being produced with realistic quotes;
3. review early trade/rejection evidence and data-quality gaps without changing v1 thresholds mid-sample;
4. implement Hyperliquid challenger registration/capital-efficiency reporting;
5. implement synchronized Polymarket event-book paper execution;
6. perform strategy reviews on fixed intervals and create new versioned challengers rather than silently retuning an existing experiment.

## V2 repair boundary — 6 September 2026

V1 implementation failed to enforce mandatory momentum/available acceleration checks and applied the entry-impact rejection gate to exits. V2 is a separate version and pair of studies with these faults repaired. V1 trades remain in the journal; v1 runs exit-only until positions are closed, then completes. Do not pool v1 and v2 performance. V2 preserves the same dollar size, stop/trail thresholds and entry impact limit, accepts full-size adverse exits with impact up to 100%, and checks all cohort exits before new entry scans. Missing quotes still do not become fills. See PROJECT_SOURCE.md for validation and deployment evidence.
