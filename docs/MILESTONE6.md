# Milestone 6 — Forward Evidence Evaluation

## Purpose

Milestone 6 turns the RED/AMBER/GREEN research rules into deterministic, auditable code.

It does **not** enable live trading. The strongest output is `GREEN-1_CANDIDATE`, which means the recorded forward evidence satisfies the pre-registered research gates and is eligible for a separate owner/security review. It does not change `Strategy.status`, fund an execution wallet, enable a signer, bridge assets, or submit an order.

## Recommendations

### RED

Evidence contains a hard failure such as:

- data-integrity failure;
- unresolved critical incident;
- non-positive realised net P&L after a trade sample exists;
- negative P&L under the configured cost-stress multiplier;
- maximum drawdown above the configured hard gate.

### AMBER

The strategy is not disproven by a hard RED condition, but evidence is incomplete or below a quality gate. Examples:

- fewer than 90 forward days;
- insufficient family-specific trade/forecast sample;
- no closed trades;
- insufficient NAV history;
- profit factor below the gate;
- profit concentrated in the top three winners;
- no shadow-execution evidence;
- low shadow fill ratio;
- excessive paper-vs-shadow price divergence;
- prediction calibration not ready;
- incomplete market-probability baseline;
- prediction Brier score does not beat the contemporaneous market baseline.

### GREEN-1_CANDIDATE

Every configured forward gate passes with no RED or AMBER reason.

This remains a **recommendation only**. A later milestone must still require explicit owner approval before any micro-live capital is released.

## Default pre-registered gates

- minimum forward period: **90 days**;
- funding: **60 closed trades** minimum;
- directional: **100 closed trades** minimum;
- memecoin: **300 closed trades** minimum;
- general/non-specialized strategies: **100 closed trades** minimum;
- prediction: **50 resolved forecasts** minimum;
- maximum drawdown: **15%**;
- minimum profit factor: **1.30**;
- maximum top-three winner concentration: **50% of total positive P&L**;
- cost stress: **2× observed fees + slippage**;
- mean shadow fill ratio: **>=90%**;
- paper-vs-shadow p90 absolute price divergence: **<=50 bps**;
- prediction calibration error: **<=0.10**.

The values are configuration, but changing them creates a new research-policy version in practice. They must not be loosened after seeing disappointing results simply to manufacture GREEN.

## Performance accounting

For every closed trade, the evaluator requires:

`net P&L = gross P&L - fees - slippage`

within a very small numeric tolerance. Planned maximum loss must be positive and cannot exceed allocated capital.

Reported metrics include:

- gross and net P&L;
- observed costs;
- stressed net P&L;
- profit factor;
- win rate;
- expectancy;
- average winner/loss;
- maximum drawdown;
- annualized Sharpe and Sortino;
- top-three profit concentration.

NAV observations may be irregularly spaced. Interval returns are converted to daily-equivalent returns before annualizing Sharpe/Sortino; a monthly observation is not falsely treated as a one-day return.

## Shadow-execution reconciliation

Paper profitability is insufficient by itself.

The evaluator compares intended/paper execution with live shadow observations and records:

- mean executable shadow fill ratio;
- p90 absolute paper-vs-shadow price divergence in basis points;
- mean shadow cost minus paper-model cost.

Filled quantity cannot exceed intended quantity. Missing shadow observations keep the strategy AMBER.

## Prediction-market evaluation

For resolved forecasts the evaluator records:

- Brier score;
- log loss;
- calibration error;
- contemporaneous market Brier score;
- Brier improvement versus the market.

The market benchmark is calculated only when **every evaluated forecast** has a matching market probability. A partial benchmark is rejected rather than compared against the full model sample.

Prediction strategies must still provide realised trade evidence, NAV history and shadow-execution evidence before they can become `GREEN-1_CANDIDATE`; probability calibration alone cannot authorize capital.

## Anti-leakage rules

Every NAV, closed trade, shadow execution and resolved forecast must fall inside the declared forward-test window.

The evaluator rejects:

- evidence before the registered forward start;
- evidence after the evaluation cutoff;
- duplicate NAV timestamps;
- non-positive NAV;
- inconsistent trade P&L;
- invalid execution quantities/prices/costs;
- invalid probabilities/outcomes.

Historical/backtest observations therefore cannot be quietly mixed into a claimed forward result.

## Persistence

Each evaluation run is immutable audit evidence containing:

- strategy slug/version/family;
- declared forward window;
- recommendation;
- observation counts;
- key metrics;
- complete policy snapshot;
- complete input snapshot;
- reasons and metric payload.

API:

- `POST /evaluation/strategy`
- `GET /evaluation/runs/{run_id}`
- `GET /evaluation/status`

The status endpoint explicitly reports that the evaluator cannot promote a strategy, enable a signer, or authorize capital.

## Safety boundary

Milestone 6 adds no:

- private keys or seed phrases;
- exchange/chain order submission;
- wallet signing;
- bridge/CCTP execution;
- vault access;
- automatic treasury transfer;
- automatic strategy promotion;
- live-capital authorization.

The global disabled signer remains unchanged.

## What comes after Milestone 6

The next practical phase is to run the collectors and paper/shadow engines continuously on the VPS long enough to accumulate genuine forward evidence. The evaluator should be run periodically against that evidence without changing its gates after results are known.

Only a strategy that later reaches `GREEN-1_CANDIDATE` should enter a separate micro-live readiness/security review. The first real-capital release remains manual and owner-controlled.
