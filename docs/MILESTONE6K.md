# Edge Lab — Milestone 6K: Stage 2 Observation Research

Status: implementation branch `feature/m6k-observation-research`; research-only; no live execution authorization.

## Purpose

M6K is the Stage 2 research layer that tries to determine whether the strongest Stage 1 observations are durable enough to justify separately registered forward hypotheses. It does not alter the frozen M6C, M6F, or M6G studies and does not promote any strategy into live execution.

M6K reuses the existing M6J research workers to avoid unnecessary services. Every M6K record is isolated by a distinct research lane:

- `m6k-hl` — Hyperliquid persistence/regime research;
- `m6k-pm` — Polymarket standard NegRisk event-consistency research;
- `m6k-sol` — Solana UNKNOWN-state decomposition and later-resolution research.

The immutable safety boundary remains:

- `SIGNER_ENABLED=false`;
- no wallet or private key;
- no venue order submission;
- no Jupiter `/execute`;
- no swaps, bridging, withdrawals, or transfers;
- no live capital;
- no automatic promotion from a research screen.

## M6K-HL — Hyperliquid persistence screen

### Question

Does a coin/horizon pair show durable funding edge after costs, rather than a temporary current-rate spike?

### Inputs

Public Hyperliquid market/funding data already collected by the M6J worker. The M6K screen uses ordered historical funding observations and the same explicit fee/slippage assumptions used by the forward study.

### Measurements

For every configured coin/horizon pair, M6K records:

- historical observation count;
- fraction of observations with positive projected edge after costs;
- fraction meeting the baseline edge threshold;
- fraction remaining positive under a configurable cost-stress multiplier;
- current and maximum baseline-edge streaks;
- funding sign flips;
- mean and standard deviation of funding;
- mean/min/max projected edge in basis points.

### Preregistered default screen

- at least 168 funding observations;
- positive edge fraction >= 0.70;
- baseline-qualified fraction >= 0.50;
- 2x-cost-stress positive fraction >= 0.50;
- current baseline-qualified streak >= 24 observations.

A pass means only `screen-only-new-forward-hypothesis-required`. It does not change M6C.

## M6K-PM — Polymarket event-consistency screen

### Question

Do complete standard Negative Risk events show persistent executable violations of the explicit mutually-exclusive/exhaustive event invariant?

### Scope

M6K only uses explicit platform metadata. It does not infer semantic relationships with an LLM and it does not use resolved outcomes.

For a complete standard NegRisk event, one YES share across every mutually exclusive outcome has deterministic total payout of one collateral unit at resolution. M6K measures the current executable ask-side cost of that complete YES basket, including current fee assumptions and common executable depth.

It records both positive and negative gaps so the dataset is not conditioned only on profitable observations.

### Fail-closed exclusions

The event-consistency observation is rejected when any of the following applies:

- event is not NegRisk;
- augmented NegRisk;
- incomplete event (<3 tradeable binary markets);
- dynamic/explicit `Other` outcome;
- unknown fee schedule;
- missing or stale order book;
- no executable ask liquidity/common depth.

### Recorded fields

- explicit event ID and market count;
- executable common quantity;
- gross cost and fees;
- total executable basket cost;
- deterministic resolution payout;
- USD gap and gap bps;
- whether the gap is positive;
- whether it clears the preregistered baseline edge threshold;
- unique public-book state key.

This observation lane does not alter M6F or create a trade record.

## M6K-SOL — Solana UNKNOWN decomposition

### Question

Which causes of an M6J `UNKNOWN` safety state are merely missing/late evidence and which are associated with bad quoteability, poor exits, or later confirmed unsafe conditions?

### Preserved decision-time rule

The original M6J decision remains immutable. Later evidence never rewrites an UNKNOWN decision into a historical SAFE decision.

### Preregistered UNKNOWN groups

- `creator_security_unknown`;
- `transfer_fee_unknown`;
- `security_snapshot_missing`;
- `asset_metadata_missing`;
- `mint_freeze_authority_unknown`;
- `non_transferable_unknown`;
- `multiple_unknown_reasons`;
- `other_unknown`.

### Observation-only measurements

For UNKNOWN candidates, M6K records:

- original decision-time feature timestamp and reasons;
- UNKNOWN group;
- quote-only entry availability;
- immediate quote-only round-trip availability and recovery ratio;
- 5/15/30/60-minute quote-only outcomes already sampled by M6J;
- quote-only P&L/return where available;
- whether later forensic/security evidence eventually resolves the state to SAFE or UNSAFE;
- resolution lag.

UNKNOWN is never treated as SAFE for the frozen M6G baseline.

## Telemetry isolation

M6K writes `ForwardScanObservation` rows using the existing active study foreign key only for analytical grouping. All M6K rows carry a separate `research_lane`. Baseline activity summaries exclude M6J and M6K lanes, and `/research` reports M6J/M6K separately.

M6K observations do not count as:

- forward trades;
- execution observations;
- NAV observations;
- evaluation sample size;
- promotion evidence.

## Configuration defaults

```text
M6K_ENABLED=true
M6K_HYPERLIQUID_MIN_OBSERVATIONS=168
M6K_HYPERLIQUID_MIN_POSITIVE_FRACTION=0.70
M6K_HYPERLIQUID_MIN_BASELINE_FRACTION=0.50
M6K_HYPERLIQUID_MIN_STRESS_POSITIVE_FRACTION=0.50
M6K_HYPERLIQUID_MIN_CURRENT_BASELINE_STREAK=24
M6K_HYPERLIQUID_COST_STRESS_MULTIPLIER=2
M6K_POLYMARKET_BASELINE_EDGE_BPS=10
M6K_SOLANA_RESOLUTION_LOOKBACK_HOURS=72
M6K_SOLANA_RESOLUTION_MAX_PER_CYCLE=100
```

These are research-screen parameters. Changing them after observing results creates a multiple-testing risk and should be documented as a new screen version rather than silently retuning `m6k-*-v1`.

## Advancement rule

M6K can identify a candidate hypothesis, but the next step is always a separately registered forward study with frozen parameters and its own evidence clock. M6K cannot authorize real-money execution, enable a signer, reuse hindsight as decision-time information, or bypass the existing evaluation gates.

## Verification requirements before deployment

1. full repository verifier passes;
2. Python compilation and Alembic fresh migration pass;
3. Docker Compose renders with `SIGNER_ENABLED=false`;
4. tests prove M6K lane isolation from baseline evidence;
5. tests prove Polymarket dynamic-Other/augmented/incomplete cases fail closed;
6. tests prove UNKNOWN remains distinct from SAFE/UNSAFE and original decisions are not rewritten;
7. deployment uses the typed Aurent Edge Lab gateway;
8. post-deployment `status` and `research-snapshot` confirm signer disabled, healthy baseline services, and distinct M6K telemetry.
