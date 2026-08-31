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

## Runtime

M6H has its own optional Docker profile:

```sh
docker compose \
  -f docker-compose.yml \
  -f deploy/compose.lifecycle.yml \
  --profile lifecycle up -d solana-lifecycle-research
```

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
- writes only to the dedicated M6H research journal and virtual policy-state tables.

Repository validation should normally use the local `scripts/verify-repo.sh` gate and targeted local checks. GitHub Actions is allowed only when a meaningful change is genuinely at the final push/finalization stage and the workflow adds useful verification or deployment value. Do not use Actions for routine iterations or unnecessary checks; see `docs/PROJECT_SOURCE.md` for the current owner policy.
