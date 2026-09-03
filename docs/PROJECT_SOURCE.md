# Edge Lab — Project Source of Truth

Living project handoff for continuing Edge Lab across chats and agents.

Last updated: 3 September 2026, Africa/Lagos

## How every future chat/agent should use this document

1. Read this file before meaningful Edge Lab implementation, deployment, research-policy, dashboard, or infrastructure work.
2. Verify the live repository state before trusting any SHA, PR state, deployment state, workflow state, or runtime assumption recorded here.
3. After meaningful work, update this same document with the new verified state, what changed, what is still unresolved, and the next exact action.
4. Keep this document operational and concise. It is a continuity source, not an unquestionable substitute for live verification.
5. Never write passwords, private keys, seed phrases, API secrets, Cloudflare tunnel tokens, Telegram bot tokens, database passwords, or other secret values here.

## Project identity

- Repository: `TropicalKenny/edge-lab`
- Primary branch: `main`
- Verified `main` HEAD before the M6I feature branch: `e18f37856d58bc028f187db05fb2086ba0f45098`
- Active implementation branch at this update: `feat/m6i-owner-controls-telegram`
- Last verified feature revision before the documentation-only follow-up commits: `aa623be03c948f8cfcc3d28824abea637936ebfb`
- Open PRs before M6I finalization: none
- `.github/workflows` on `main`: absent
- A temporary feature-branch-only verification workflow was used once for final M6I verification and then removed before merge preparation.

Always fetch current HEAD before continuing because this document update itself advances the feature branch.

## Product purpose

Edge Lab is a research-only quantitative/market-structure laboratory. Current work is focused on collecting forward evidence for several strategy families, evaluating them under realistic simulated execution/cost assumptions, and exposing the results through owner-facing read and control surfaces.

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

A VPS-local dashboard mode now also exists so Dashboard V1 can be health-checked on `127.0.0.1:8080` before Cloudflare is configured.

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

Cloudflare is a gateway only. Edge Lab application/runtime state remains on the VPS.

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

M6H records timestamped lifecycle observations, executable quote-only marks, liquidity/security/momentum context, independent policy state and counterfactual outcomes. Re-entry is deliberately fail-closed and every policy decision remains `can_execute=false`.

See `docs/MILESTONE6H_LIFECYCLE_RESEARCH.md`.

### M6H lifecycle performance accounting

Merged via PR #38.

Merge commit: `d61f523dae662b1417d97fc935a1ee20953f1e0e`

Implemented:

- deterministic, idempotent replay for every position and policy;
- uninterrupted-hold and policy-path values on the same observation timeline;
- exact Jupiter quote amount/value capture for scaled re-entry accounting;
- versioned conservative cost assumptions;
- complete-cycle records and per-observation performance snapshots;
- net/excess return, cost drag, MFE/MAE, capture, downside, time-in-state, round-trip, failed-re-entry, and missed-recovery measurements;
- sample gates of at least 300 complete positions and 300 completed cycles before a policy can enter registered walk-forward comparison;
- a fail-closed lifecycle-only launcher that keeps `SIGNER_ENABLED=false`.

The performance layer analyzes hypothetical outcomes only. It cannot execute, promote a policy, or mutate the frozen M6G entry baseline.

### M6I owner-control core + Telegram — implemented on feature branch

The deterministic M6I control plane and Telegram owner surface are implemented and verified on `feat/m6i-owner-controls-telegram`.

Implemented control architecture:

- dedicated `edge_control` PostgreSQL role;
- exact read grants for owner performance/status views;
- only column-scoped writes to existing research tables (`forward_studies.status`, operational incident resolution fields);
- no DELETE grant and no all-table write grant;
- typed allowlisted `OwnerControlService`;
- durable command audit with idempotency, actor, reason, timestamps and outcome;
- separate lifecycle enable/disable state so M6H can stop without mutating M6G;
- permanent data-integrity incidents cannot be resolved away;
- private bearer-authenticated owner-control API intended for VPS loopback `127.0.0.1:8090`;
- dedicated Telegram long-polling worker with no inbound public port;
- Telegram authorization requires both configured private chat id and owner user id;
- durable Telegram update cursor;
- Telegram read commands for status, simulated balance/NAV, P&L, performance, strategies, evidence and incidents;
- Telegram mutation commands for pause/resume/freeze, M6H lifecycle toggle and incident acknowledgement/resolution;
- Telegram and private owner API share the same command engine/audit path;
- no shell, Docker socket, signer, venue credentials, wallet material or live-capital capability is exposed to either control surface.

Read `docs/OWNER_CONTROLS.md` before changing M6I behavior.

### VPS baseline that works before Solana provider keys

A separate launch path now exists specifically so Helius/Jupiter do not block useful deployment:

```sh
sh deploy/start-vps-without-solana-keys.sh
```

It is designed to start:

- PostgreSQL + migrations + backups;
- Hyperliquid paper/shadow collection;
- Polymarket paper/shadow collection;
- forward evaluator;
- frozen Solana M6G study registration without starting Solana network workers;
- read-only dashboard on VPS loopback `127.0.0.1:8080`;
- private owner-control API on VPS loopback `127.0.0.1:8090`;
- Telegram owner controls;
- Telegram owner alerts.

Solana launch/forensic/M6G/M6H network workers remain deliberately off until Helius/Jupiter are configured.

## Current verification and runtime state

Final M6I feature verification ran on GitHub Actions only because this was a meaningful push/finalization stage allowed by the owner Actions policy. The temporary workflow was removed afterward and is not intended for `main`.

Verified on 3 September 2026 against feature revision `aa623be03c948f8cfcc3d28824abea637936ebfb`:

- all **196 tests passed**;
- Python compilation passed;
- shell syntax passed for the new M6I/core launchers;
- a fresh Alembic migration reached `l2d59a86c177` successfully;
- the full Docker Compose stack rendered successfully with non-secret verification placeholders;
- the VPS-local dashboard Compose stack rendered successfully;
- final verification job `100555956472` / run `33726305077` completed successfully.

The verification emitted pre-existing framework/OpenAPI warnings but no failing test or verification step.

Important runtime distinction:

- the M6I code/deployment configuration is verified;
- **the new M6I/Edge Lab baseline has not yet been verified as running on the OVH VPS**;
- no claim should be made that Hyperliquid/Polymarket are accumulating evidence until VPS deployment/runtime health is actually checked;
- Helius/Jupiter are intentionally deferred by owner instruction until the non-Solana baseline is working.

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

The one-time M6I final-verification workflow was justified by rule 3 and removed after the successful run. Do not recreate persistent CI on `main` merely because that verification existed.

## Development / Git workflow

Preferred pattern:

1. Inspect current `main` and open PRs first.
2. Work on a focused branch for meaningful implementation.
3. Run targeted local/direct checks while developing.
4. Review the diff for scope and safety.
5. Run the appropriate repository verification before claiming completion.
6. Only at the final push/merge/deployment stage decide whether GitHub Actions is useful enough to run.
7. Merge only after the actual validation evidence supports it.
8. Update this source document after the meaningful change.

## Current exact continuation target

Immediate target: **merge/deploy the verified M6I + Telegram branch to the OVH VPS and prove the non-Solana baseline healthy before adding Helius/Jupiter**.

Deployment order:

1. Review the final branch diff and merge only if no scope/safety regression is found.
2. On the VPS, update/clone `TropicalKenny/edge-lab` from the merged `main`.
3. Run VPS host checks if not already verified for this repository.
4. Run `sh deploy/init-forward-env.sh` only if `deploy/.env.forward` does not already exist; never overwrite an existing protected env file.
5. Add the dedicated Edge Lab Telegram bot token/chat identity directly on the VPS, not in Git or chat history.
6. Run `sh deploy/start-vps-without-solana-keys.sh`.
7. Verify Hyperliquid/Polymarket collectors, evaluator, backups, local dashboard, private owner API, Telegram controls and Telegram alert channel.
8. Confirm `/status`, `/balance`, `/pnl` and a reversible pause/resume control from Telegram.
9. Begin the initial 24-hour soak for the public-data research collectors.
10. Only after that baseline is healthy, add Helius/Jupiter and start Solana M6G/M6H through the existing full preflight paths.

### Remaining M6I web work

The shared mutation service/private API is implemented, but the browser-facing authenticated site-control adapter is still outstanding. When added, it must:

- keep `edge_dashboard` exact-table SELECT-only;
- proxy typed commands to the separate owner-control service rather than giving the dashboard DB write rights;
- validate real Cloudflare Access identity cryptographically at the application boundary;
- add CSRF protection;
- never expose the private owner bearer token to browser JavaScript;
- preserve the same audit/idempotency semantics as Telegram.

This web adapter is not required to start the VPS paper/shadow evidence collection or use Telegram controls.

### Readiness estimate

- **Hyperliquid/Polymarket paper-shadow collection:** code/config verified and ready for VPS runtime deployment now; provider keys are not required.
- **Telegram owner operation:** code/config verified; requires the dedicated Telegram values in the VPS environment and runtime deployment.
- **Solana M6G/M6H collection:** waits only on VPS baseline verification plus Helius/Jupiter configuration.
- **Browser owner controls:** shared backend is implemented; Cloudflare-authenticated browser adapter remains.
- **Real money:** not authorized and not close; requires forward evidence, separate micro-live security design and explicit owner approval.

## Important design distinction

Keep these separate:

- **entry decision** — frozen M6G baseline;
- **hold/exit decision** — M6H lifecycle policy;
- **re-entry decision** — M6H post-sale policy;
- **hindsight scoring** — research evaluation only;
- **owner controls** — research-operational state only, never strategy/live-capital authority.

Do not merge these into one opaque model.

## Files likely relevant to continuation

Core continuity:

- `docs/PROJECT_SOURCE.md`
- `docs/OWNER_CONTROLS.md`
- `docs/DEPLOYMENT_HANDOFF.md`
- `docs/MILESTONE6H_LIFECYCLE_RESEARCH.md`

M6I:

- `app/control_models.py`
- `app/control_service.py`
- `app/owner_control_server.py`
- `app/telegram_control.py`
- `app/workers/telegram_controls.py`
- `alembic/versions/l2d59a86c177_add_owner_controls.py`
- `deploy/compose.controls.yml`
- `deploy/preflight-controls.sh`
- `deploy/start-control-plane.sh`
- `deploy/compose.dashboard-local.yml`
- `deploy/start-dashboard-local.sh`
- `deploy/preflight-core-forward.sh`
- `deploy/start-core-forward.sh`
- `deploy/start-vps-without-solana-keys.sh`
- `tests/test_owner_controls.py`
- `tests/test_telegram_controls.py`
- `tests/test_control_deployment.py`

Lifecycle/reference:

- `app/lifecycle_models.py`
- `app/lifecycle_research.py`
- `app/solana_lifecycle.py`
- `app/workers/solana_lifecycle_research.py`
- `app/lifecycle_performance.py`
- `deploy/compose.lifecycle.yml`
- `deploy/start-lifecycle.sh`
- `app/solana_forward.py` — frozen baseline reference; avoid accidental mutation
- `scripts/verify-repo.sh`

## What the next chat should do first

1. Read this document.
2. Fetch current `main`, feature-branch/PR state and Actions state before assuming the M6I branch was merged.
3. If not merged, review `main...feat/m6i-owner-controls-telegram`, then merge only if the verified scope remains intact.
4. Do not claim VPS deployment until runtime evidence proves it.
5. Deploy the no-Solana-keys baseline first and verify Telegram + Hyperliquid/Polymarket operation.
6. Keep Helius/Jupiter deferred until the owner is ready to add them.
7. Preserve all research-only safety boundaries and the deliberate GitHub Actions policy.

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

This document preserves continuity. Live repository, deployment, database and runtime evidence remains authoritative. Always verify current state before acting.
