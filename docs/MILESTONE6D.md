# Milestone 6D — Forward Study Bootstrap and Unattended Operations

## Purpose

Milestone 6D turns the merged M6C Hyperliquid paper/shadow runner into an operable forward-research service without adding any live trading capability.

The forward profile now has four responsibilities:

1. migrate the database;
2. idempotently bootstrap the frozen Hyperliquid carry study;
3. run the public-data-only paper/shadow forward worker;
4. write at most one recommendation-only evidence evaluation per active study per UTC day.

A read-only status command exposes whether the study is ready, waiting for fresh observations, or blocked by a permanent evidence-integrity problem.

## Frozen bootstrap

Run directly:

```text
python -m app.forward_ops bootstrap
```

Or start the complete Docker profile:

```text
docker compose --profile forward up -d
```

`hyperliquid-forward-bootstrap` is a one-shot service. The forward runner and evaluator do not start until it completes successfully.

The bootstrap is idempotent. The default study identity is:

```text
external id: hyperliquid-btc-carry-m6c-v1
strategy:    hyperliquid-funding-carry
version:     m6c-v1
code SHA:    649496cd08bbcb7ad6d5c4cfd61ae44412fabdc4
instrument:  BTC
```

The code SHA is the merged M6C strategy implementation. M6D adds orchestration around that runner; it does not silently relabel a changed strategy as the old immutable version.

On first bootstrap the service registers:

- a RED strategy record if it does not already exist;
- an immutable strategy version tied to the M6C code SHA;
- a deterministic experiment ID derived from the forward study external ID;
- a frozen `ForwardStudy` using the current configured evaluation policy and carry assumptions;
- the initial simulated NAV at the exact study start time.

On later bootstrap attempts, the existing study is reused only when its strategy lineage, instrument, simulated capital, frozen runner configuration and frozen evaluation policy still match exactly. Configuration drift fails closed rather than changing a running study retroactively.

To start a genuinely different experiment, use a new external ID and, when strategy logic changes, a new immutable strategy version/code SHA. Do not overwrite the existing study.

## Default simulated study settings

The default environment values are research defaults, not real-money allocations:

```text
HYPERLIQUID_FORWARD_INITIAL_CAPITAL_USD=1000
HYPERLIQUID_FORWARD_PAIRED_NOTIONAL_USD=100
HYPERLIQUID_FORWARD_HORIZON_HOURS=24
HYPERLIQUID_FORWARD_MIN_EDGE_BPS=10
HYPERLIQUID_FORWARD_PLANNED_LOSS_PCT=0.02
HYPERLIQUID_FORWARD_SHADOW_DELAY_MS=1000
```

All fee, slippage, oracle-age, exit-delay and Milestone-6 evaluation thresholds are frozen into database JSON at study creation.

## Read-only status

```text
python -m app.forward_ops status
```

For one study:

```text
python -m app.forward_ops status --external-id hyperliquid-btc-carry-m6c-v1
```

For a machine health check:

```text
python -m app.forward_ops status \
  --external-id hyperliquid-btc-carry-m6c-v1 \
  --require-ready --quiet
```

Exit codes:

- `0`: selected study/studies are ready, or status was requested without `--require-ready`;
- `2`: no selected study exists when readiness was required;
- `3`: at least one selected study is waiting or blocked;
- `1`: invalid configuration or another operations error.

The Docker forward runner uses this command as its health check.

Status reports include:

- frozen strategy/version/code SHA;
- strategy status (the bootstrap never promotes it);
- study age and current status;
- latest NAV and time;
- open position count;
- trade and paper/shadow execution counts;
- incident counts;
- permanent data-integrity failure count;
- unresolved critical incident count;
- latest Hyperliquid market and funding observations;
- latest evidence recommendation.

Operational states are:

- `ready`: no blocking evidence/lineage condition and observations are fresh;
- `waiting`: the study is structurally valid but a market observation is missing/stale;
- `blocked`: the study is non-active, malformed, contaminated, has an unresolved critical incident, has impossible position state, or lacks required funding evidence for an aged open position.

## Permanent integrity stop

The operational runner checks the forward-study incident journal **before calling Hyperliquid**.

If any data-integrity failure has ever been recorded for that study, the runner returns `blocked` and makes no new market calls. This is permanent because Milestone 6 counts all data-integrity failures in the evidence gate, including incidents that were later operationally resolved.

An unresolved critical incident also pauses the worker. Unlike a data-integrity failure, a non-integrity critical incident may resume after it is explicitly resolved.

The system therefore never attempts to “trade through” or dilute a contaminated research record with later observations.

## Daily evidence evaluation

The one-shot command is:

```text
python -m app.forward_ops evaluate
```

The Docker service `forward-evaluator` checks hourly by default but writes at most one evaluation per active study per UTC day.

It calls the frozen M6B evidence evaluator. It may emit only:

- `RED`
- `AMBER`
- `GREEN-1_CANDIDATE`

It does **not**:

- mutate `Strategy.status`;
- complete the study;
- enable a signer;
- authorize capital;
- place an order;
- bridge or transfer funds.

A GREEN candidate remains only an evidence recommendation for a later explicit promotion decision.

## Docker forward profile

The forward profile contains:

```text
hyperliquid-forward-bootstrap  one-shot frozen registration
hyperliquid-forward-runner     public books/funding -> paper/shadow evidence
forward-evaluator              daily recommendation-only evidence scoring
```

The runner and evaluator both depend on successful bootstrap. Every forward service explicitly sets `SIGNER_ENABLED=false`.

The normal API and other collectors remain independent of the forward profile.

## Safety boundary

Milestone 6D adds no account credentials, wallet fields, signing key, authenticated Hyperliquid endpoint, `/exchange` action, transfer/bridge path, vault access, live order route, live-capital authorization, or automatic strategy promotion.
