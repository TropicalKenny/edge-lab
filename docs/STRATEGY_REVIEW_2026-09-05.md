# Edge Lab — Stage 1 Strategy & Evidence Review

Date: 5 September 2026

Purpose: determine what the first two days of forward and accelerated observation actually justify changing, what must remain frozen, and what the next research lanes should test. This document does **not** authorize live capital, signing, wallet access, venue order submission, or automatic strategy promotion.

## Executive decision

The current evidence is sufficient for a **strategy-design review**, but not for a strategy-performance or promotion decision.

Keep all frozen M6C/M6F/M6G controls intact. Do not reinterpret zero-trade baselines as failed or successful trading systems. Use the accumulated M6J evidence to decide where additional observation is likely to produce information fastest.

Priority order for the next research phase:

1. **Hyperliquid — highest near-term research priority.** The broad carry surface shows repeated positive projected edge, but the current M6J acceptance count is too optimistic to treat as a strategy result because it extrapolates the current hourly funding rate across long horizons. Build persistence/regime evidence before opening a new forward variant.
2. **Solana — second priority.** The baseline is currently bottlenecked by incomplete safety evidence rather than proven negative expectancy. Continue counterfactual outcome collection and decompose UNKNOWN candidates by missing security field before changing any hard gate.
3. **Polymarket — demote the current immediate complete-set thesis to control status.** The scanner is working at high frequency but has observed no positive structural edge. Do not spend the next research cycle merely waiting on the same narrow hypothesis. Add a separate combinatorial/event-consistency research lane instead of weakening the current control.

No frozen control should be edited in place.

## Evidence used

Fresh VPS research snapshot captured 2026-09-05T14:20:20Z through the read-only Aurent typed gateway:

- three active forward studies;
- $3,000 simulated initial capital and $3,000 latest simulated NAV;
- 0 closed forward trades;
- 0 shadow execution observations;
- 0 permanent data-integrity incidents;
- 0 contaminated studies;
- all three venue studies operationally `ready`;
- all strategy evaluations still AMBER because evidence gates are not met.

Important interpretation rule: M6J scan/check counts are repeated forward observations, not independent trades or independent experiments. They measure search coverage and persistence, not sample size for promotion.

The existing promotion framework remains authoritative. In particular, M6H treats fewer than 300 complete positions/cycles as `INSUFFICIENT_SAMPLE`, and reaching that count only qualifies a candidate for a separately registered walk-forward study.

## 1. Hyperliquid — M6C + M6J

### Current control

M6C is a BTC long-spot / short-perp funding carry study with:

- 24-hour horizon;
- 10 bps minimum expected edge;
- conservative base taker fees of 7.0 bps spot and 4.5 bps perp;
- 2 bps slippage reserve per leg;
- no leverage in the research model.

The frozen BTC control examined 287 opportunities in the latest 24-hour snapshot and accepted 0. All 287 were rejected for `EDGE_BELOW_THRESHOLD`; 26 observations also had non-positive funding.

### What M6J added

M6J observes BTC, ETH and SOL across 24h, 7d, 14d and 30d horizons. In the latest 24-hour snapshot it recorded:

- 384 coin/horizon observations;
- 131 positive current projected-edge observations;
- 253 non-positive observations.

This is a useful signal, but **131 must not be read as 131 profitable opportunities**.

The current M6J positive classification uses:

`current_hourly_funding × horizon - estimated round-trip costs`

and accepts the observation when that number is positive. For 7/14/30-day horizons, this assumes the *current* hourly funding rate persists across the full horizon. The worker also stores trailing 7-day and 30-day projected edge, but those fields do not determine the current accepted count.

Therefore the broad result means:

> there are combinations where current funding is high enough to overcome the cost model if it persists;

not:

> the strategy has demonstrated a persistent 7/14/30-day carry edge.

### External evidence

Hyperliquid itself documents hourly funding driven by premium/oracle conditions and notes that the rate changes with the market; current funding is not a guaranteed future cash flow. Hyperliquid's base fee schedule also matches Edge Lab's conservative 4.5 bps perp / 7.0 bps spot assumptions for a zero-volume taker account.

Recent academic work on crypto carry similarly finds that funding/carry can be large but is volatile and assumption-sensitive, with profitability materially affected by funding compression, execution frictions, venue risk and regime changes.

### Decision

**KEEP M6C frozen. EXPAND research, not the control.**

The next Hyperliquid lane should test persistence and regime robustness rather than simply adding more horizons.

### Recommended next experiment: M6K-HL persistence study

Observation-only. No forward trade creation yet.

For each `(coin, horizon)` combination, record and aggregate:

- current projected edge;
- trailing 24h, 7d and 30d funding-implied edge;
- fraction of observations above 0 bps and above the 10 bps baseline threshold;
- consecutive hours above threshold;
- funding sign flips;
- funding volatility;
- basis level and basis change;
- estimated costs at baseline and 2x cost stress;
- maximum adverse basis move over the proposed holding horizon;
- liquidity/depth adequacy for the intended notional;
- per-coin/per-horizon observation counts.

A candidate should not advance to a new forward variant unless it shows positive edge under both a persistence test and cost stress. The exact threshold must be preregistered before results are used for selection.

Do **not** select the best coin/horizon retrospectively from the same data and then claim it as validated. Selection creates a new hypothesis; the chosen variant needs a fresh forward study.

## 2. Polymarket — M6F + M6J

### Current control

M6F deliberately tests only immediate deterministic structural conversions:

- binary complete-set buy/merge;
- standard NegRisk NO complete-set conversion/merge;
- current CLOB fees;
- explicit operation-cost reserve;
- delayed shadow book confirmation;
- full-depth execution only.

That narrowness is a strength for causal interpretation, but it also means the strategy can be structurally too rare to justify continued primary research attention.

### Current accelerated evidence

Latest 24-hour M6J aggregate:

- about 1.38 million WebSocket messages;
- 63,582 book events / binary checks;
- 6,048 NegRisk checks;
- 69,630 total pair/event checks;
- 0 positive-edge events;
- 0 events clearing the frozen 10 bps baseline threshold.

These are repeated book-state checks, not 69,630 independent markets. Still, they show that the current high-liquidity universe is being observed frequently and the immediate structural opportunity is not appearing in the sampled states.

The largest rejection groups were:

- `NO_EXECUTABLE_EDGE`;
- `STALE_BOOK`;
- `NO_ASK_LIQUIDITY`;
- incomplete NegRisk events;
- CLOB market metadata mismatch.

### Fee-model sanity check

The repository is already compatible with Polymarket CLOB V2 fee metadata: `apply_clob_market_info()` reads the current `fd` fee object (`r`, `e`, `to`) and replaces the Gamma fee schedule before analysis. The 2% fee buffer is a 2% uplift to the calculated fee, not a 2-percentage-point fee. Therefore the zero-edge result is not explained by an obviously stale V1 fee parser.

### External evidence

Current Polymarket documentation confirms a CLOB with taker-only fees on fee-enabled markets and no maker fee. Recent empirical research on Polymarket order books finds single-market arbitrage extremely rare and short-lived, while combinatorial inefficiencies across related markets occur more often but are still constrained by liquidity and execution timing.

That is directionally consistent with Edge Lab's current result: an immediate same-market complete-set strategy can be too efficient to generate enough forward trades, even while broader combinatorial inconsistencies still exist elsewhere in the event graph.

### Decision

**KEEP M6F running as a low-cost frozen control, but stop treating it as the leading Polymarket alpha thesis.**

Do not lower the edge threshold merely to manufacture trades. Do not remove the delayed-book or complete-depth rules. Those would change the question instead of answering it.

### Recommended next experiment: M6K-PM event-consistency lane

Observation-only and separate from M6F.

Research deterministic or logically constrained relationships across *related* markets/events, for example:

- mutually exclusive outcome groups whose executable ask sums violate a complete probability bound;
- nested questions where one outcome logically implies another;
- same-event strike/range markets with monotonicity violations;
- tournament/series trees with inconsistent parent/child probabilities;
- complete NegRisk event combinations outside the current immediate NO-only basket when payout logic can be represented without outcome leakage.

Requirements:

- relationships must be generated from explicit market/event metadata, not semantic guessing by an LLM;
- every relationship type must have a machine-checkable logical invariant;
- use executable bid/ask depth, not displayed midpoint;
- record opportunity duration and executable size;
- retain fee-aware and delayed-book stress;
- separate discovery from later evaluation to avoid hindsight selection;
- do not use resolved outcomes to construct the relationship set.

Do not prioritize cross-platform Polymarket/Kalshi arbitrage yet. Recent work shows that apparent cross-platform arbitrage can disappear after true timestamp alignment and fees; adding venue matching risk now would complicate the evidence before the internal event-consistency lane is exhausted.

## 3. Solana — M6G + M6J

### Current control

M6G is intentionally a safety-first baseline, not a tuned meme strategy. It will only quote an entry when decision-time security evidence is explicitly complete and clean, including:

- mint authority not active;
- freeze authority not active;
- transferable token;
- creator not flagged malicious;
- transfer fee exactly zero;
- positive DEX liquidity;
- prior exit evidence;
- acceptable exit price impact.

### Current evidence

Latest baseline activity:

- 55 candidates examined;
- 0 accepted;
- 55 rejected;
- dominant reasons include creator security not clean/known and transfer-fee not zero-or-known;
- 30 also lacked preflight exit impact/value evidence.

M6J classified the same evidence surface more carefully:

- 55 UNKNOWN;
- 0 SAFE;
- 0 UNSAFE;
- 55 counterfactual quote attempts;
- 48 entry quotes;
- 24 immediate round-trip quotes;
- 187 time-horizon outcome observations.

This distinction matters. The data does **not** currently say all candidates were dangerous. It says the frozen control lacked enough explicit safety evidence to call any of them clean.

Solana's Token Extensions make this caution appropriate: transfer fees, non-transferability, frozen default account states and other extensions can materially alter exitability. Unknown should not be silently treated as safe.

### Decision

**KEEP M6G frozen. Do not loosen UNKNOWN into SAFE.**

The current bottleneck is observability/classification quality. Before changing alpha filters, determine which unknown fields cause the gate and whether those fields can be resolved deterministically from chain data or a more reliable security source.

### Recommended next experiment: M6K-SOL unknown-decomposition study

Extend observation-only telemetry so every UNKNOWN candidate is grouped by missing reason and later outcome:

- creator-security unknown only;
- transfer-fee unknown only;
- security snapshot missing;
- asset metadata missing;
- mint/freeze authority unknown;
- non-transferable unknown;
- multiple unknown reasons.

For each group, calculate:

- Jupiter entry quote availability;
- immediate round-trip recovery ratio;
- exit-route availability at 5/15/30/60m;
- counterfactual return distribution;
- route disappearance rate;
- price impact distribution;
- liquidity trajectory;
- later evidence that resolves the original UNKNOWN to SAFE or UNSAFE, without altering the original decision record.

This will answer whether the main problem is:

1. unavailable security data;
2. overly broad use of a probabilistic creator reputation field as a hard cleanliness requirement;
3. genuinely dangerous/token-extension-heavy launches;
4. poor exitability independent of security classification.

Only after that decomposition should a new Solana entry variant be preregistered.

## 4. Portfolio-level strategy conclusion

Do not choose a live strategy now. There is no performance evidence yet.

For research allocation, use:

- **50% research attention: Hyperliquid persistence/regime carry** — most promising path to near-term forward opportunities, but current long-horizon positives need validation.
- **30%: Solana unknown-decomposition + counterfactual outcomes** — current system is learning useful things, but classification coverage is the bottleneck.
- **20%: Polymarket combinatorial/event-consistency research** — retain the immediate structural lane as a control while shifting discovery toward logically related markets.

This allocation is research prioritization only; it does not allocate capital.

## 5. What should not change

Do not:

- modify M6C, M6F or M6G frozen configs in place;
- reinterpret M6J scan counts as independent trade samples;
- lower thresholds merely to create trades;
- use future outcome information in entry features;
- optimize many thresholds on the same two-day sample and report the winner;
- enable wallet/signing/order submission;
- treat an operationally `ready` study as strategy validation;
- treat a current projected funding edge as a guaranteed multi-day funding stream;
- treat Solana UNKNOWN as SAFE;
- delete historical non-integrity incidents from the research journal.

## 6. Stage 2 implementation plan

If approved, implement the next research milestone as three observation-only sublanes under a single M6K milestone:

### M6K-HL

Add persistence/regime aggregation for M6J Hyperliquid telemetry and preregister advancement criteria for a future separate forward study.

### M6K-PM

Add metadata-derived event-consistency/combinatorial invariant checks with executable-depth and opportunity-duration telemetry. Keep M6F untouched.

### M6K-SOL

Add UNKNOWN reason/outcome decomposition and later-resolution tracking. Keep M6G untouched.

### Shared requirements

- no wallet;
- no signer;
- no transaction/order submission;
- no changes to frozen baseline journals;
- new tables/telemetry must be namespaced and migration-backed;
- all selection criteria fixed before using resulting observations to choose a forward variant;
- local `scripts/verify-repo.sh` before final push;
- deploy only after review of migration, security boundary and research-integrity invariants;
- update `PROJECT_SOURCE.md` and `DEPLOYMENT_HANDOFF.md` after implementation/deployment.

## Sources consulted

Project evidence:

- `docs/PROJECT_SOURCE.md`
- `docs/MILESTONE6F.md`
- `docs/MILESTONE6G.md`
- `docs/MILESTONE6H_LIFECYCLE_RESEARCH.md`
- `docs/MILESTONE6J.md`
- `app/config.py`
- `app/venues/hyperliquid.py`
- `app/workers/m6j_hyperliquid_research.py`
- `app/workers/m6j_polymarket_research.py`
- `app/workers/m6j_solana_research.py`
- `app/research_acceleration.py`
- `app/venues/polymarket_validation.py`
- fresh VPS `research-snapshot` at 2026-09-05T14:20:20Z

External references checked on 5 September 2026:

- Hyperliquid Docs — Funding: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding
- Hyperliquid Docs — Fees: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees
- Polymarket Docs — Fees: https://docs.polymarket.com/trading/fees
- Polymarket Docs — Market WebSocket: https://docs.polymarket.com/api-reference/wss/market
- Polymarket Docs — CLOB V2 migration: https://docs.polymarket.com/v2-migration
- Solana Docs — Transfer Fees: https://solana.com/docs/tokens/extensions/transfer-fees
- Solana Docs — Token Extensions: https://solana.com/docs/tokens/extensions
- Schmeling & Todorov, `Crypto Carry`, Management Science, 2026
- Pindza, `Centralized–decentralized exchange funding rate arbitrage as a basis trade`, Digital Finance, 2026
- Cheng, Yang & Zou, `Arbitrage Analysis in Polymarket NBA Markets`, 2026
- Saguillo et al., `Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets`, 2025

## Review status

Stage 1 complete.

Recommended next action: implement M6K as observation-only research acceleration. No strategy is approved for live capital.