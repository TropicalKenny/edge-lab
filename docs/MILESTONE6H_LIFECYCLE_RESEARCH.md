# Milestone 6H — Adaptive Hold, Exit, Wait and Re-entry Research

M6H is a separate forward-shadow research layer. It does **not** change the frozen
M6G Solana Pump baseline and it does not authorize live capital, signing, swap
submission, bridging or fund movement.

## Research question

For an opportunity that the frozen baseline already entered, M6H asks four
separate questions using only information available at each timestamp:

1. Is continuing to **HOLD** preferable?
2. Is the move strong enough to **TAKE_PROFIT**?
3. After a virtual sale, should the policy **WAIT** or **ABANDON**?
4. After a pullback, are price, liquidity, momentum, sell pressure and quote
   quality strong enough to justify a virtual **REENTER**?

The initial policies are hypotheses, not promoted strategies:

- `tp30-rebuy15`
- `tp50-rebuy20`
- `tp80-rebuy25`

Each policy owns independent virtual state. One policy can take profit while
another continues holding. A policy that virtually sells can later re-enter and
repeat the cycle without modifying the baseline position.

## Evidence journal

`lifecycle_observations` records quote-only marks plus contemporaneous Solana
forensic features. M6H captures:

- executable token-to-USDC mark value and price impact;
- quote-only USDC-to-token re-entry availability and price impact;
- liquidity and liquidity relative to the original entry snapshot;
- momentum, five-minute sell ratio and volume acceleration;
- a conservative security-clean signal;
- baseline entry/exit context for auditability.

Forensic confirmation is rejected when the latest feature snapshot is older
than `LIFECYCLE_MAX_FEATURE_AGE_MINUTES`. Re-entry also requires an explicitly
clean security signal plus acceptable liquidity, momentum, volume acceleration
and sell pressure. A dip by itself is never enough to produce `REENTER`.

`lifecycle_policy_states` stores each policy's virtual invested/cash/abandoned
state. `lifecycle_policy_decisions` stores every HOLD, TAKE_PROFIT, WAIT,
REENTER or ABANDON decision with `can_execute=false`.

## Counterfactual scoring

`lifecycle_decision_outcomes` resolves earlier decisions at 5, 15, 30, 60 and
180 minute horizons only after those observations exist. Future data is used
only for scoring. It is never fed back into the earlier decision.

This explicitly separates:

- information available when the decision was made; and
- hindsight used later to determine whether that decision was useful.

The first outcome layer measures subsequent market movement, MFE and MAE. It
does not claim that hindsight discovered a perfect top or bottom.

## Lifecycle performance accounting

`m6h-performance-v1` adds deterministic policy-level accounting without
changing M6G or making any decision executable.

For every policy observation it records:

- virtual policy value beside the uninterrupted-hold liquidation value;
- net and excess return after costs;
- observed quote deterioration plus a frozen conservative reserve of 20 bps
  and $0.01 per virtual transaction leg;
- cumulative cost drag;
- MFE, MAE and MFE capture ratio;
- downside avoided or incurred relative to hold;
- time invested versus time in cash;
- completed invested cycles and round trips;
- failed re-entry cycles; and
- missed recovery cases while a policy remains in cash.

Executable Jupiter quote outputs already include the quoted market impact, so
that impact is not subtracted twice. The additional reserve covers deterioration
between observation and hypothetical fill. The common frozen M6G entry cost is
excluded from the M6H comparison because every lifecycle policy starts from the
same already-entered baseline position.

New observations retain exact quote amounts and USD values used by the replay.
Older rows without that detail can be replayed only through an explicitly marked
normalized-value fallback and remain incomplete for selection purposes.

Accounting rows live in:

- `lifecycle_performance_snapshots`; and
- `lifecycle_policy_cycles`.

The lifecycle worker backfills missing accounting rows deterministically before
adding the newest observation. The journal is versioned and idempotent.

Policy summaries remain non-promotional. Fewer than 300 complete positions or
300 completed cycles is automatically `INSUFFICIENT_SAMPLE`. Reaching those
counts only makes a policy ready for a separately registered walk-forward study;
it does not rank, promote or authorize the policy automatically.

## Runtime

M6H has its own optional Docker profile:

```sh
sh deploy/start-lifecycle.sh
```

The launcher runs the private-research preflight before rendering and starting
the lifecycle profile.

Defaults:

```text
LIFECYCLE_POLL_SECONDS=60
LIFECYCLE_MAX_OBSERVATION_AGE_MINUTES=1440
LIFECYCLE_MAX_FEATURE_AGE_MINUTES=15
```

The worker refuses to start when `SIGNER_ENABLED=true` and requires only the
existing Jupiter data/API credential needed for quote-only observation. To
reduce provider usage, the reverse USDC-to-token quote is requested only while
at least one virtual policy is actually in the cash/waiting state.

## Safety boundary

M6H:

- has no wallet or private key input;
- has no taker address;
- never requests Jupiter execution;
- never submits a transaction or order;
- cannot move funds;
- cannot mutate M6G;
- cannot promote itself to live trading;
- writes only to the dedicated M6H research, virtual policy-state and
  performance-accounting tables.

Repository validation should normally use the local `scripts/verify-repo.sh` gate and targeted local checks. GitHub Actions is allowed only when a meaningful change is genuinely at the final push/finalization stage and the workflow adds useful verification or deployment value. Do not use Actions for routine iterations or unnecessary checks; see `docs/PROJECT_SOURCE.md` for the current owner policy.
