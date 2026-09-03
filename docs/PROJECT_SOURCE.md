# Edge Lab — Project Source of Truth

Living project handoff for continuing Edge Lab across chats and agents.

Last updated: 3 September 2026, Africa/Lagos

## How every future chat/agent should use this document

1. Read this file before meaningful Edge Lab implementation, deployment, research-policy, dashboard, or infrastructure work.
2. Verify the live repository and VPS state before trusting any SHA, deployment state, workflow state, or runtime assumption recorded here.
3. After meaningful work, update this file with the new verified state, unresolved items, and next exact action.
4. Never write passwords, private keys, seed phrases, API secrets, Cloudflare tunnel tokens, Telegram bot tokens, database passwords, or other secret values here.
5. Live repository, deployment, database and runtime evidence remains authoritative.

## Project identity

- Repository: `TropicalKenny/edge-lab`
- Primary branch: `main`
- M6I PR: #39 — `feat(m6i): add VPS owner controls and Telegram operations`
- M6I merge commit: `aba54c2a2acdf5ee82c2deb81048063c60b9125d`
- Current verified VPS revision after deployment fixes: `ca118ce4bf5b08faae730ed76a699542d0033865`
- VPS checkout: `/home/ubuntu/workspace/edge-lab`
- VPS host: OVH, Ubuntu user `ubuntu`

Always fetch current `main` before acting because later documentation or fixes may have advanced it beyond the verified VPS revision above.

## Product purpose and safety boundary

Edge Lab is a research-only quantitative/market-structure laboratory. It collects forward evidence, evaluates strategy families under simulated execution/cost assumptions, and exposes owner-facing research status/control surfaces.

It is **not authorized** for live capital, signing, order submission, Jupiter execution, swaps, bridging, withdrawals, transfers, automatic strategy promotion, or owner-vault access.

`SIGNER_ENABLED=false` is mandatory for the current milestone.

Any future micro-live milestone requires a separate security review and explicit owner authorization.

## Frozen forward-research families

### Hyperliquid

- Funding/carry paper-shadow forward research.
- Public/research data only.
- No order submission or signer.

### Polymarket

- Structural complete-set / immediate structural paper-shadow research.
- No live capital or order submission.

### Solana Pump — M6G

- Frozen launch baseline.
- Chain-native launch discovery.
- Quote-only Jupiter usage.
- Entry baseline remains intentionally unchanged by M6H lifecycle research.
- No Jupiter `/execute`, taker address, wallet, signer, bridge, transfer or transaction submission.

### M6H lifecycle research

M6H remains separate from the frozen M6G baseline and studies:

- `HOLD`
- `TAKE_PROFIT`
- `WAIT`
- `REENTER`
- `ABANDON`

Initial hypothesis policies:

- `tp30-rebuy15`
- `tp50-rebuy20`
- `tp80-rebuy25`

Every policy remains hypothetical and `can_execute=false`.

M6H performance accounting was merged in PR #38, merge commit `d61f523dae662b1417d97fc935a1ee20953f1e0e`.

## M6I owner controls — merged and deployed

M6I is no longer a feature-branch-only milestone. PR #39 is merged and the control plane is deployed on the OVH VPS.

Implemented architecture:

- dedicated `edge_control` PostgreSQL role;
- exact read grants for owner research/status views;
- only column-scoped writes to approved research-operational fields;
- no DELETE grant and no all-table write grant;
- typed allowlisted `OwnerControlService`;
- durable command audit and idempotency;
- separate M6H lifecycle enable/disable state;
- data-integrity incidents cannot be resolved away;
- private owner-control API on VPS loopback `127.0.0.1:8090`;
- dedicated Telegram long-polling worker, no inbound public port;
- Telegram authorization requires both configured private chat ID and owner user ID;
- Telegram and private owner API share the same typed command engine;
- no shell, Docker socket, signer, wallet material, venue execution credential or live-capital capability is exposed to the owner control surfaces.

Telegram read commands:

- `/help`
- `/status`
- `/balance`
- `/pnl`
- `/performance`
- `/strategies`
- `/evidence`
- `/incidents`

Telegram research controls:

- `/pause <solana|polymarket|hyperliquid|all> [reason]`
- `/resume <target> [reason]`
- `/freeze <target> [reason]`
- `/lifecycle on|off [reason]`
- `/incident ack|resolve <incident-id> [reason]`

There is no ordinary owner unfreeze command.

Read `docs/OWNER_CONTROLS.md` before changing M6I behavior.

## ChatGPT → Aurent → VPS typed operations gateway

A durable typed VPS operations path now exists and is the preferred way for ChatGPT to operate Edge Lab without asking the owner to type routine Termius commands.

Architecture:

`ChatGPT → Aurent typed VPS gateway → OVH VPS → Edge Lab`

The gateway is owned by `TropicalKenny/aurent-design-intelligence` and uses Aurent's existing protected VPS SSH credential. Edge Lab does not receive or expose that private key.

Aurent gateway files:

- `.github/workflows/vps-ops-gateway.yml`
- `ops/vps-request.json`
- `scripts/vps/edge-lab-ops.sh`

Installed VPS runner:

`/usr/local/sbin/aurent-edge-lab-ops`

Allowlisted Edge Lab operations:

- `status`
- `update`
- `preflight-baseline`
- `start-baseline`
- `restart-baseline`
- `preflight-full`
- `start-full`
- `restart-full`

The gateway:

- is hard-bound to project `edge-lab`;
- validates operation names before SSH and again on the VPS;
- does not accept arbitrary shell commands;
- fails if tracked VPS working-tree changes exist before updating;
- uses `git pull --ff-only` on `main`;
- reports secrets only as `SET`/`MISSING`, never values;
- reports signer state, Docker container state, restart counts and loopback health;
- can return redacted Telegram diagnostics if that worker restarts;
- does not expose root shell, wallet material or live execution capability.

Future chats should use this gateway for normal Edge Lab VPS status/update/preflight/start/restart tasks instead of defaulting to manual Termius instructions.

GitHub Actions remains subject to the owner's deliberate-use policy: do not use Actions for routine coding iterations. This gateway is justified for explicit remote VPS operations where the run itself performs the requested deployment/status task.

## Current VPS credential state

Verified without exposing values:

- `JUPITER_API_KEY=SET`
- `HELIUS_API_KEY=MISSING`
- `TELEGRAM_BOT_TOKEN=SET`
- `TELEGRAM_CHAT_ID=SET`
- `TELEGRAM_OWNER_USER_ID=SET`
- `SIGNER_ENABLED=false`

Do not ask the owner to paste these secret values into chat.

Helius is the remaining provider blocker for the actual Solana network workers.

## Current deployed baseline

The no-Solana-keys baseline has been deployed successfully with:

`sh deploy/start-vps-without-solana-keys.sh`

Verified running on the VPS:

- PostgreSQL;
- Redis;
- migrations;
- database backups;
- Edge Lab internal API on loopback `127.0.0.1:8000`;
- Hyperliquid collector;
- Hyperliquid forward runner process;
- Polymarket collector;
- Polymarket forward runner;
- forward evaluator;
- frozen Solana M6G study registration with Solana network workers idle;
- read-only dashboard on loopback `127.0.0.1:8080`;
- private owner-control API on loopback `127.0.0.1:8090`;
- Telegram owner controls;
- Telegram owner alerts.

Still intentionally disabled until Helius is configured:

- Solana launch collector;
- Solana forensic sampler;
- Solana M6G forward runner;
- M6H lifecycle observer/accounting worker.

### Verified health

Dashboard health returns:

- `status=ok`
- `mode=dashboard-read-only`
- `can_trade_live=false`
- `can_sign=false`
- `can_move_funds=false`
- `live_capital_usd=0`

Owner-control health returns:

- `status=ok`
- `can_trade_live=false`
- `can_sign=false`
- `can_move_funds=false`
- `shell_access=false`

Polymarket forward runner reached Docker `healthy`.

All observed baseline container restart counts were `0` after the Telegram fix.

### Hyperliquid readiness caveat

The Hyperliquid collector and forward-runner processes are running and have restart count `0`, but the last verification still showed the forward runner as `health: starting`, not yet `healthy`.

Do **not** claim Hyperliquid forward evidence is fully ready/accumulating until its `--require-ready` health check passes. Its Docker health check runs:

`python -m app.forward_ops status --external-id "$HYPERLIQUID_FORWARD_STUDY_EXTERNAL_ID" --require-ready --quiet`

This is the remaining baseline readiness item to inspect before declaring the whole non-Solana baseline fully healthy.

### Core `/health` caveat

The legacy internal API `/health` currently reports aggregate `healthy=false` because its in-process registry defaults `market_data` to `no-live-collector` and `reconciliation` to `not-wired` even though separate collector containers are running. Treat this as legacy/misleading aggregate health semantics, not evidence that the deployed collector containers have crashed.

Do not change that endpoint casually; fix it only with a scoped health-model review.

## Deployment fixes made during live VPS rollout

### API port merge bug

Initial baseline preflight failed because Docker Compose merged base `8000:8000` with the hardened `127.0.0.1:8000:8000` override.

Fixed by making the forward override explicitly replace the port list:

```yaml
ports: !override
  - "127.0.0.1:8000:8000"
```

Fix commit: `8ccc3d350be71560bb84aed20a677a5cfd5e3ab1`.

### Backup path cleanup

Forward backups now use `deploy/backups/`, matching the safety tooling and `.gitignore`. The old root `backups/` path is ignored rather than destructively removed.

### Telegram long-poll transaction bug

The first deployed Telegram controls worker repeatedly restarted because it opened a PostgreSQL transaction and then kept it open while awaiting Telegram long polling. PostgreSQL correctly terminated the idle transaction.

Fixed in `app/workers/telegram_controls.py` so:

- cursor reads use a short DB session;
- the DB session closes before Telegram `getUpdates` long polling;
- command read/mutation work uses a short DB session;
- the DB session closes before `sendMessage`;
- the durable update cursor advances in a new short DB session only after a successful send;
- mutating commands remain idempotent across retries.

Fix commit: `ca118ce4bf5b08faae730ed76a699542d0033865`.

After redeployment, Telegram controls stayed up across multiple long-poll windows with restart count `0`. Telegram API calls returned HTTP 200.

## Verification history relevant to M6I

Feature verification before merge:

- 196 tests passed;
- Python compilation passed;
- shell syntax passed;
- fresh Alembic migration reached `l2d59a86c177`;
- full Docker Compose render passed;
- VPS-local dashboard Compose render passed;
- one-time final verification run `33726305077`, job `100555956472`, succeeded;
- temporary feature verification workflow was removed afterward.

Live typed-gateway deployment/verification runs included:

- initial typed status: run `33733841374`;
- baseline start: run `33733899386`;
- post-start status/diagnostics and cleanup runs;
- Telegram transaction-fix deployment: run `33734817246`;
- Telegram fix verification: run `33735022712`;
- final stability status: run `33735211530`.

These Actions runs were operationally justified because they directly performed/verified the requested remote VPS deployment through the typed gateway. Do not turn them into general CI churn.

## Dashboard and browser-control status

The local read-only dashboard is running on `127.0.0.1:8080`.

Cloudflare publication is not yet configured; `CLOUDFLARE_TUNNEL_TOKEN` may remain blank until that step.

The browser-facing authenticated mutation adapter is still outstanding. When added, it must:

- keep `edge_dashboard` exact-table SELECT-only;
- proxy typed mutations to the separate owner-control service;
- validate Cloudflare Access identity cryptographically;
- add CSRF protection;
- never expose the private owner bearer token to browser JavaScript;
- preserve the Telegram/API audit and idempotency semantics;
- never expose the private owner-control API directly to the public internet.

## Research integrity rules

All continuing strategy/lifecycle research must guard against:

- look-ahead bias;
- survivorship bias;
- leakage from final outcomes into decision-time features;
- cherry-picked horizons;
- multiple-testing / strategy overfitting;
- inconsistent cost/slippage assumptions;
- treating oracle/hindsight exits as decision-time information.

Use hindsight only as a scoring benchmark after a decision was timestamped.

Prefer simple, interpretable policies before ML/RL. Contextual bandits/RL remain later-stage research only after enough evidence and proper off-policy evaluation design.

## Important design distinction

Keep these separate:

- **entry decision** — frozen M6G baseline;
- **hold/exit decision** — M6H lifecycle policy;
- **re-entry decision** — M6H post-sale policy;
- **hindsight scoring** — research evaluation only;
- **owner controls** — research-operational state only, never strategy/live-capital authority.

Do not merge these into one opaque model.

## GitHub Actions policy — owner instruction

GitHub Actions is allowed, but use it deliberately.

1. Do not use Actions for routine coding iterations, exploratory research, branch inspection, ordinary local tests, or unnecessary automation.
2. Prefer targeted local/direct verification while developing.
3. Use Actions when a meaningful final verification/deployment or typed remote VPS operation genuinely requires it.
4. Avoid repeated runs merely to check progress that can be verified another way.
5. Avoid workflow churn and surprise billing.
6. A push does not automatically require Actions.

## Files likely relevant to continuation

Core continuity:

- `docs/PROJECT_SOURCE.md`
- `docs/OWNER_CONTROLS.md`
- `docs/DEPLOYMENT_HANDOFF.md`
- `docs/MILESTONE6H_LIFECYCLE_RESEARCH.md`

M6I / owner controls:

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

Aurent remote operations:

- `TropicalKenny/aurent-design-intelligence/.github/workflows/vps-ops-gateway.yml`
- `TropicalKenny/aurent-design-intelligence/ops/vps-request.json`
- `TropicalKenny/aurent-design-intelligence/scripts/vps/edge-lab-ops.sh`

## Current exact continuation target

1. Diagnose/confirm Hyperliquid forward-runner readiness without changing the frozen research baseline.
2. Continue the non-Solana paper/shadow soak once Hyperliquid reports ready.
3. Obtain/configure Helius when its dashboard is accessible; Jupiter is already configured.
4. Run the full research preflight through the Aurent typed gateway.
5. Only if preflight passes, use the typed `start-full` operation to start Solana M6G/M6H network research.
6. Later publish the read-only dashboard through Cloudflare and build the authenticated browser mutation adapter.
7. Preserve `SIGNER_ENABLED=false` and all research-only boundaries.

## What the next chat should do first

1. Read this document.
2. Fetch current Edge Lab `main` and current Aurent typed-gateway state.
3. Use the Aurent typed `status` path to inspect the VPS rather than asking the owner for manual Termius commands.
4. Check whether Hyperliquid is now `healthy` or diagnose its readiness failure if not.
5. Keep full Solana network workers off until `HELIUS_API_KEY` is configured and the full preflight passes.
6. Never expose or request secret values in chat.

## Source-of-truth rule

This document preserves continuity. Live repository, deployment, database and runtime evidence remains authoritative. Always verify current state before acting.
