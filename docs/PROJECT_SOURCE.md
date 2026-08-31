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
- Verified `main` HEAD after M6H performance merge and before this handoff update: `d61f523dae662b1417d97fc935a1ee20953f1e0e`
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

### M6H lifecycle performance accounting

Merged via PR #38.

Merge commit: `d61f523dae662b1417d97fc935a1ee20953f1e0e`

Implemented after the initial M6H state machine:

- deterministic, idempotent replay for every position and policy;
- uninterrupted-hold and policy-path values on the same observation timeline;
- exact Jupiter quote amount/value capture for scaled re-entry accounting;
- versioned cost assumptions with quote deterioration plus a conservative extra reserve;
- complete-cycle records and per-observation performance snapshots;
- net/excess return, cost drag, MFE/MAE, capture, downside, time-in-state,
  round-trip, failed-re-entry, and missed-recovery measurements;
- sample gates of at least 300 complete positions and 300 completed cycles before
  a policy can enter registered walk-forward comparison;
- a fail-closed lifecycle-only launcher that keeps `SIGNER_ENABLED=false`.

The performance layer analyzes hypothetical outcomes only. It cannot execute,
promote a policy, or mutate the frozen M6G entry baseline.

## Current verification and runtime state

Verified locally on 31 August 2026:

- `scripts/verify-repo.sh` passed;
- all 180 tests passed;
- Python compilation passed;
- a fresh Alembic migration reached `k1c48f75b066` successfully;
- shell syntax for `deploy/start-lifecycle.sh` passed;
- Docker Compose rendering was skipped because Docker is unavailable in the
  current workspace.

No active VPS deployment, running collectors, or accumulating 90-day evidence
was verified. The repository is deploy-ready research software, not a confirmed
running research system.

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

Next owner milestone: **M6I authenticated research controls from the site**.

The site should support a deliberately small command allowlist:

- pause and resume evidence collection;
- freeze a study so no further observations are accepted;
- acknowledge or resolve an operational incident without deleting its record;
- enable or disable M6H lifecycle observation for a frozen study configuration;
- show command status, actor identity, timestamp, reason, and outcome.

Required architecture and safety rules:

1. Keep the existing dashboard database identity exact-table SELECT-only.
2. Put mutations behind a separate owner-control service and dedicated
   least-privilege database role.
3. Accept only typed, allowlisted research commands with idempotency keys,
   reasons, audit records, and fail-closed state transitions.
4. Validate Cloudflare Access identity at the application boundary and add CSRF
   protection; do not trust a browser header alone.
5. Do not expose the Docker socket, shell commands, internal ingest secret,
   venue credentials, wallet material, or a general-purpose internal API proxy.
6. Site controls must never sign, trade, swap, bridge, withdraw, transfer funds,
   promote a strategy, or enable live capital.
7. Add lifecycle performance reporting after the accounting schema has soaked
   under real paper/shadow collection.

The control plane is an owner-experience requirement, but it is not a prerequisite
for starting paper/shadow evidence collection from the VPS.

### Readiness estimate

- **Start collecting paper/shadow evidence:** close. With the VPS, PostgreSQL,
  Cloudflare, and required public-data API credentials configured, launch can be
  attempted the same day, followed by a 24-hour soak before trusting unattended
  collection.
- **Use Edge Lab as an owner-operated research product:** one meaningful milestone
  away: M6I site controls plus deployment/runtime verification.
- **Use real money:** not close and not authorized. That requires the forward
  evidence period (target roughly 90 days), a separate micro-live security design,
  and explicit owner approval.

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
- `app/lifecycle_performance.py`
- `alembic/versions/j0b37e64a955_add_lifecycle_research.py`
- `alembic/versions/k1c48f75b066_add_lifecycle_performance.py`
- `deploy/compose.lifecycle.yml`
- `deploy/start-lifecycle.sh`
- `tests/test_lifecycle_research.py`
- `tests/test_lifecycle_performance.py`
- `app/solana_forward.py` — frozen baseline reference; avoid accidental mutation
- `scripts/verify-repo.sh`

## What the next chat should do first

1. Read `docs/PROJECT_SOURCE.md`.
2. Fetch current `main` HEAD and compare it with this handoff.
3. Check open PRs and current workflow/Actions state.
4. Inspect any commits made after this handoff before editing.
5. Read `docs/MILESTONE6H_LIFECYCLE_RESEARCH.md` and the relevant lifecycle code/tests.
6. Continue with the M6I authenticated owner research controls unless the owner gives a different priority.
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
