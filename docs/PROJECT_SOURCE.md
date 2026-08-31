# Edge Lab — Project Source of Truth

Living project handoff for continuing Edge Lab across chats and agents.

Last updated: 31 August 2026, Africa/Lagos

## How every future chat/agent should use this document

1. Read this file before meaningful Edge Lab implementation, deployment, research-policy, dashboard, or infrastructure work.
2. Verify the live repository state before trusting any SHA, PR state, deployment state, workflow state, or runtime assumption recorded here.
3. After meaningful work, update this same document with the new verified state, what changed, what is still unresolved, and the next exact action.
4. Keep this document operational and concise. It is a continuity source, not an unquestionable substitute for live verification.
5. Never write passwords, private keys, seed phrases, API secrets, Cloudflare tunnel tokens, Telegram bot tokens, database passwords, or other secret values here.

## Project identity

- Repository: `TropicalKenny/edge-lab`
- Primary branch: `main`
- Verified project-state HEAD before this handoff-document commit: `85acb85cda2d325e0252d9c323a457e2020a63c3`
- Open PRs at handoff: none
- GitHub Actions running at handoff: 0 in progress, 0 queued
- `.github/workflows` on `main` at handoff: absent

The handoff-document commit itself advances `main`, so always fetch current HEAD before continuing.

## Product purpose

Edge Lab is a research-only quantitative/market-structure laboratory. Current work is focused on collecting forward evidence for several strategy families, evaluating them under realistic simulated execution/cost assumptions, and exposing the results through a read-only owner dashboard.

It is not authorized for live capital, signing, order submission, swaps, bridging, withdrawals, or automatic strategy promotion.

## Frozen forward-research baseline families

### Hyperliquid

- Funding/carry paper-shadow forward research.
- Public/research data only.
- No order submission or live signer.

### Polymarket

- Structural complete-set / immediate structural paper-shadow research.
- No live capital or order submission.

### Solana Pump — M6G

- Frozen launch baseline.
- Chain-native launch discovery.
- Quote-only Jupiter usage.
- Entry baseline remains intentionally unchanged by later lifecycle research.
- No Jupiter `/execute`, taker address, wallet, signer, bridge, transfer, or transaction submission.

## Major completed milestones relevant to continuation

### M6G — Solana Pump baseline forward study

Merged previously and treated as frozen entry/exit baseline research.

Important rule: do not silently tune or mutate M6G while evaluating later lifecycle ideas. Any later hold/exit/re-entry work must remain a separate research layer until evidence justifies a formal new baseline.

### Dashboard V1

Read-only research dashboard is implemented.

Key properties:

- research evidence only;
- no live-trading controls;
- no signer controls;
- no fund movement;
- isolated Cloudflare-facing dashboard service;
- full internal API is not the public tunnel target;
- dashboard PostgreSQL role is read-only and constrained by an exact-table allowlist;
- local static assets; no requirement for third-party browser analytics/CDNs.

See `docs/DASHBOARD_V1.md` and `docs/DEPLOYMENT_HANDOFF.md` for operational details.

### VPS / Cloudflare / preflight work

Implemented:

- isolated Cloudflare Tunnel + Access topology;
- `dashboard:8080` as the intended Cloudflare-facing service;
- internal API remains loopback/private;
- PostgreSQL and Redis not publicly exposed;
- fail-closed deployment preflight and runtime verification;
- Ubuntu VPS provisioning/readiness scripts;
- optional durable Telegram owner-alert path;
- local repository verification gate at `scripts/verify-repo.sh`.

### M6H — Adaptive hold, exit, wait and re-entry research

Merged via PR #37.

Merge commit: `85acb85cda2d325e0252d9c323a457e2020a63c3`

M6H is a separate forward-shadow lifecycle layer built on observations after the frozen M6G baseline has entered.

It studies these decisions independently:

- `HOLD`
- `TAKE_PROFIT`
- `WAIT`
- `REENTER`
- `ABANDON`

Initial hypothesis policies:

- `tp30-rebuy15`
- `tp50-rebuy20`
- `tp80-rebuy25`

Each policy has independent virtual state. One policy may take profit while another continues holding. A virtually sold policy may later wait and re-enter without changing the real/frozen M6G baseline state.

M6H records:

- timestamped lifecycle observations;
- quote-only mark values and price impact;
- reverse quote availability only when a policy is actually waiting to re-enter;
- liquidity and liquidity relative to the original entry snapshot;
- momentum;
- five-minute sell ratio;
- volume acceleration;
- security-clean confirmation;
- baseline entry/exit context;
- policy state and decision history;
- counterfactual outcomes at 5, 15, 30, 60, and 180-minute horizons.

Re-entry is deliberately fail-closed. A dip alone is insufficient. It requires an explicitly clean security state, acceptable liquidity, momentum, volume acceleration, sell pressure, and quote quality. Stale forensic features cannot authorize re-entry.

Every M6H policy decision remains `can_execute=false`.

See `docs/MILESTONE6H_LIFECYCLE_RESEARCH.md`.

## Current M6H verification state

Verified during implementation:

- new M6H Python files were syntax-checked;
- lifecycle Compose YAML parsed successfully;
- isolated lifecycle state-machine tests passed 6/6;
- tested behavior includes virtual sell -> cash/wait -> confirmed re-entry;
- missing quote behavior fails toward HOLD/WAIT rather than inventing an executable decision.

Do not claim that the complete repository verification suite has passed unless `scripts/verify-repo.sh` is actually run in the appropriate local/VPS environment after syncing current `main`.

## Research integrity rules

All continuing lifecycle/strategy research must guard against:

- look-ahead bias;
- survivorship bias, especially for launch-token datasets;
- leakage from final outcomes into decision-time features;
- cherry-picked horizons;
- multiple-testing / strategy overfitting;
- inconsistent cost/slippage assumptions;
- treating oracle/hindsight exits as something available at decision time.

Use hindsight only as a scoring benchmark after a decision was already timestamped.

Prefer simple, interpretable policies before ML/RL. Contextual bandits/RL remain later-stage research only after sufficient evidence volume and proper off-policy evaluation design.

## Safety boundary — non-negotiable unless the owner explicitly creates a later live-capital milestone

Current Edge Lab research must not:

- import or expose wallet/private keys or seed phrases;
- enable a live signer;
- submit venue orders;
- call Jupiter execution;
- move, bridge, withdraw, or transfer funds;
- allow AI to control owner-vault credentials;
- automatically promote a research strategy to live capital;
- treat `GREEN-1_CANDIDATE` or any positive research result as permission to trade live.

`SIGNER_ENABLED=false` remains the expected research setting.

Any future micro-live milestone requires a separate security review and explicit owner authorization.

## GitHub Actions policy — current owner instruction

GitHub Actions is **allowed**, but it must be used deliberately.

Rules:

1. Do **not** use GitHub Actions for routine coding iterations, exploratory research, branch inspection, ordinary local tests, small validation loops, or unnecessary automation.
2. During development, prefer targeted local/direct verification first.
3. GitHub Actions may be enabled/used when it is genuinely time to push/finalize a meaningful change and the workflow provides useful final verification or deployment value.
4. Do not create repeated Actions runs merely to check progress that could have been verified locally.
5. Avoid unnecessary workflow churn and surprise billing.
6. Before reintroducing or enabling a workflow, inspect the current repo state and make sure that workflow is actually justified for the push/release/deployment being performed.
7. A push does not automatically require Actions. Use Actions only when it adds value at that stage.

At this handoff, no workflow exists on `main`, and no Action is running or queued. Do not recreate CI merely because it existed historically.

## Development / Git workflow

Preferred pattern:

1. Inspect current `main` and open PRs first.
2. Work on a focused branch for meaningful implementation.
3. Run targeted local/direct checks while developing.
4. Review the diff for scope and safety.
5. Run the appropriate local repository verification before claiming completion.
6. Only at the final push/merge/deployment stage decide whether GitHub Actions is useful enough to run.
7. Merge only after the actual validation evidence supports it.
8. Update this source document after the meaningful change.

Do not use Actions as a substitute for understanding the code or for repeated low-value checks.

## Current exact continuation target

Next research layer: **M6H lifecycle performance engine**.

Primary question:

> Do repeated virtual sell/wait/re-entry policies actually outperform simple holding after consistent hypothetical slippage, quote deterioration, and other modeled costs?

Build this as evidence analysis, not execution logic.

### Recommended next implementation sequence

1. Add policy-level lifecycle accounting across complete virtual cycles.
2. Compute realized/virtual lifecycle P&L consistently for:
   - uninterrupted hold baseline;
   - each take-profit/rebuy policy;
   - each completed virtual re-entry cycle.
3. Apply consistent simulated costs/slippage to all compared paths.
4. Add capture metrics, including:
   - return relative to hold;
   - excess return after costs;
   - MFE capture ratio;
   - MAE / downside avoided or incurred;
   - number of round trips;
   - cost drag;
   - time invested vs time in cash;
   - failed re-entry / missed-recovery cases;
   - tail-loss behavior.
5. Rank policies only after sufficient observations; do not promote from tiny samples.
6. Use walk-forward/out-of-sample evaluation where policy thresholds are being compared or selected.
7. Keep policy thresholds as hypotheses until evidence justifies a new registered challenger/baseline.
8. Add read-only dashboard reporting later, after the accounting/evaluation layer is stable.

### Important design distinction

Keep these separate:

- **entry decision** — frozen M6G baseline;
- **hold/exit decision** — M6H lifecycle policy;
- **re-entry decision** — M6H post-sale policy;
- **hindsight scoring** — research evaluation only.

Do not merge these into one opaque model.

## Files likely relevant to continuation

- `docs/PROJECT_SOURCE.md` — this living source document
- `docs/MILESTONE6H_LIFECYCLE_RESEARCH.md`
- `docs/DEPLOYMENT_HANDOFF.md`
- `app/lifecycle_models.py`
- `app/lifecycle_research.py`
- `app/solana_lifecycle.py`
- `app/workers/solana_lifecycle_research.py`
- `alembic/versions/j0b37e64a955_add_lifecycle_research.py`
- `deploy/compose.lifecycle.yml`
- `tests/test_lifecycle_research.py`
- `app/solana_forward.py` — frozen baseline reference; avoid accidental mutation
- `scripts/verify-repo.sh`

## What the next chat should do first

1. Read `docs/PROJECT_SOURCE.md`.
2. Fetch current `main` HEAD and compare it with this handoff.
3. Check open PRs and current workflow/Actions state.
4. Inspect any commits made after this handoff before editing.
5. Read `docs/MILESTONE6H_LIFECYCLE_RESEARCH.md` and the relevant lifecycle code/tests.
6. Continue with the M6H lifecycle performance engine unless the owner gives a different priority.
7. Preserve research-only safety boundaries.
8. Do not use GitHub Actions unnecessarily; only consider it at the final push/finalization stage when it adds value.

## Handoff update template

After meaningful work, update this file with:

- Last updated: [date/time]
- Verified repo HEAD / branch: [branch + SHA]
- Merged since previous handoff: [PRs / concise purpose]
- Verification actually executed: [only what truly ran]
- Runtime/deployment state: [only what was verified]
- Open issues / paused work: [short list]
- GitHub Actions state/use: [why it was or was not used]
- Next exact action: [single most important continuation step]

## Source-of-truth rule

This document preserves continuity. Live repository, deployment, database, and runtime evidence remains authoritative. Always verify current state before acting.