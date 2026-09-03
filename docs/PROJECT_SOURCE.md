# Edge Lab — Project Source of Truth

Living project handoff for continuing Edge Lab across chats and agents.

Last updated: 3 September 2026, Africa/Lagos

## How every future chat/agent should use this document

1. Read this file before meaningful Edge Lab implementation, deployment, research-policy, dashboard, Telegram, or infrastructure work.
2. Verify live repository/VPS state before trusting any recorded SHA or runtime state.
3. After meaningful work, update this document and `docs/DEPLOYMENT_HANDOFF.md`.
4. Never write passwords, private keys, seed phrases, API secrets, database passwords, Telegram tokens, Cloudflare tokens, or provider URLs containing credentials here.
5. Live repository, database, deployment, and runtime evidence is authoritative.

## Current verified state

Repository: `TropicalKenny/edge-lab`

Primary branch: `main`

VPS checkout: `/home/ubuntu/workspace/edge-lab`

VPS host: OVH, Ubuntu user `ubuntu`

Verified deployed runtime code revision:

`f454e7fb64eb117278fcc8f1def1153d896cf39e`

That revision is PR #49, `feat: add Telegram paper trade and daily heartbeat alerts`.

Current `main` may become newer after documentation-only commits. Do not redeploy merely because documentation advances `main`; compare changed files first.

### Settled live verification — 3 September 2026

Aurent typed status run `33749858549` verified after the PR #49 deployment:

- deployed SHA: `f454e7fb64eb117278fcc8f1def1153d896cf39e`;
- Hyperliquid forward runner: `healthy`;
- Polymarket forward runner: `healthy`;
- Solana forward runner: `healthy`;
- PostgreSQL: healthy;
- dashboard: healthy on `127.0.0.1:8080`;
- owner-control API: healthy on `127.0.0.1:8090`;
- internal API remains loopback `127.0.0.1:8000`;
- Telegram controls running;
- Telegram alerts running;
- M6H lifecycle research running;
- all observed container restart counts: `0`;
- persisted Telegram command menu still matches the safe 14-command list;
- `SIGNER_ENABLED=false`.

The post-alert read-only research snapshot run `33749917961`, captured at `2026-09-03T11:29:11Z`, reported all three forward studies operationally `ready` with no hard reasons or warnings:

- Hyperliquid — `ready`;
- Polymarket — `ready`;
- Solana — `ready`.

It also reported:

- simulated research capital: `$3,000` total across three independent `$1,000` paper/shadow studies;
- current simulated NAV: `$3,000`;
- closed trades: `0` at that capture time;
- open Hyperliquid positions: `0`;
- open Solana positions: `0`;
- execution observations: `0`;
- permanent data-integrity incidents: `0`;
- contaminated studies: `0`;
- unresolved incidents: `6`, all historical non-data-integrity provider/parser errors fixed earlier the same day.

Do not interpret those historical incidents as current venue failures when readiness is fresh and `ready`.

## Product purpose and immutable current safety boundary

Edge Lab is a research-only quantitative/market-structure laboratory. It collects forward evidence, evaluates strategy families under simulated execution/cost assumptions, and provides owner-facing research status/control surfaces.

Current milestone rules:

- no live capital;
- no wallet or owner-vault access;
- no transaction signing;
- no venue order submission;
- no Jupiter `/execute`;
- no swaps, bridging, withdrawals, or transfers;
- no automatic strategy promotion into live execution;
- `SIGNER_ENABLED=false` is mandatory.

Any future micro-live milestone requires a separate security review and explicit owner authorization. Never infer authorization from a GREEN/evidence result.

## Research families currently running

### Hyperliquid — M6C funding/carry

Paper/shadow funding/carry research is running.

Final current parser contract fix:

- `spotMetaAndAssetCtxs` can contain more contexts than listed markets;
- each listed spot market uses its explicit `market["index"]` to select `contexts[market["index"]]`;
- referenced context rows are still validated fail-closed;
- a narrow equal-length/no-identity fallback remains only for legacy deterministic fixtures.

Final parser merge: `1d5f795ce8a8932663c8890fd038b0d85cdddbb4`.

Earlier schema drift was also fixed through a proper Alembic migration rather than manual production ALTER statements.

Current live state: `ready` / Docker `healthy`.

Historical unresolved non-integrity incidents include old `spot metadata/context length mismatch` and `unknown spot context identity: @71` errors. They predate the final parser and should not be treated as current failures if market/funding timestamps remain fresh.

### Polymarket — M6F immediate structural

Paper/shadow structural research is running.

On 3 September 2026 the Gamma keyset API rejected the old sort parameter:

`order=liquidity_num` → HTTP 422, `order fields are not valid`.

A public live matrix confirmed:

- minimal keyset query → 200;
- `liquidity_num` → 422;
- `liquidityNum` → 200;
- `liquidity` → 200;
- `volume` → 200;
- `volume_num` → 422.

Edge Lab now uses the current keyset sort field:

`order=liquidityNum`

The fix and regression coverage remain in the current runtime lineage.

Current live state: `ready` / Docker `healthy`.

The three historical `PM_FORWARD_UNEXPECTED` 422 incidents remain in the journal as non-data-integrity history.

### Solana Pump — M6G frozen entry baseline

The Solana Pump baseline is running against a standard Solana RPC provider through configured HTTP + WebSocket URLs.

Current provider state, verified without exposing values:

- `SOLANA_RPC_HTTP_URL=SET`;
- `SOLANA_RPC_WS_URL=SET`;
- `JUPITER_API_KEY=SET`;
- `HELIUS_API_KEY=MISSING`;
- Helius is **not a current blocker** because Edge Lab now supports the standard RPC provider path and the live full stack is already running through it.

The active standard RPC provider is Alchemy. Do not put its credential-bearing URL in documentation or chat.

M6G remains frozen as the entry baseline:

- chain-native launch discovery;
- quote-only Jupiter usage;
- no taker address;
- no wallet;
- no signer;
- no transaction submission.

Current live state: `ready` / Docker `healthy`.

### M6H lifecycle research

M6H remains separate from the frozen M6G entry baseline. The lifecycle worker is running.

Research actions remain hypothetical/non-executable, including:

- `HOLD`;
- `TAKE_PROFIT`;
- `WAIT`;
- `REENTER`;
- `ABANDON`.

Initial policies include `tp30-rebuy15`, `tp50-rebuy20`, and `tp80-rebuy25`.

Keep entry decision, hold/exit decision, re-entry decision, and hindsight scoring separate. Do not collapse them into one opaque model.

## M6I owner controls

PR #39 is merged; merge commit:

`aba54c2a2acdf5ee82c2deb81048063c60b9125d`

Implemented boundaries:

- dedicated least-privilege `edge_control` PostgreSQL role;
- typed `OwnerControlService`;
- durable command audit/idempotency;
- private owner-control API on `127.0.0.1:8090`;
- Telegram long polling with no inbound public port;
- authorization requires both configured owner chat ID and owner user ID;
- no shell, Docker socket, wallet, signer, venue execution, or fund-movement capability.

Typed mutation commands remain limited to:

- pause;
- resume;
- freeze;
- lifecycle on/off;
- incident acknowledge/resolve.

There is no ordinary owner unfreeze command. Data-integrity incidents cannot be resolved away.

Read `docs/OWNER_CONTROLS.md` before changing these semantics.

## Telegram owner interface — current verified menu

Current commands:

- `/research` — consolidated read-only research snapshot;
- `/status`;
- `/performance`;
- `/evidence`;
- `/strategies`;
- `/balance`;
- `/pnl`;
- `/incidents`;
- `/pause`;
- `/resume`;
- `/freeze`;
- `/lifecycle`;
- `/incident`;
- `/help`.

`/snapshot` is a hidden alias for the research snapshot but is not required in the menu.

### Stale Kennysbot menu incident and final fix

The owner's iPhone previously displayed legacy commands such as `/sell`, `/sellall`, `/stop`, `/papermode`, `/golive`, `/confirm`, `/tp`, `/sl`, `/strict`, `/loose`, `/setbuysol`, `/pending`, `/approve`, and `/reject` after the default Telegram menu had been corrected.

Root cause: Telegram persists command lists independently by BotCommandScope and language. Default-scope verification alone was insufficient.

Runtime writes the safe Edge Lab menu at Telegram worker startup to six variants:

1. default / generic language;
2. default / English;
3. all-private-chats / generic;
4. all-private-chats / English;
5. exact owner chat / generic;
6. exact owner chat / English.

One-time live API verification run `33747154288` queried all six variants. Every variant returned exactly the safe 14-command menu:

- missing commands: none;
- unexpected commands: none;
- `all_scopes_ok=true`.

Settled post-PR #49 status run `33749858549` again verified the persisted safe menu and `telegram_menu_ok=true`.

If a mobile Telegram client still visually shows the legacy menu after this verified server state, treat it as client-side cached UI before changing server code again.

## Telegram paper/shadow trade alerts and daily heartbeat

PR #49 merged as runtime revision:

`f454e7fb64eb117278fcc8f1def1153d896cf39e`

The owner-alert worker now sends durable Telegram notifications for research activity while preserving the no-live-capital boundary.

### Paper/shadow open alerts

- Hyperliquid: one alert per durable `HyperliquidCarryPosition` row;
- Solana: one alert per accepted M6G entry execution with `phase=entry` and `status=open`;
- rejected Solana candidates do not alert;
- messages include venue/study/instrument, simulated allocation, entry details, timestamp/planned hold or close, and an explicit `PAPER/SHADOW ONLY` warning.

Polymarket's current M6F structure is immediate/completion-style rather than a durable open position, so it does not fabricate an open-position notification.

### Paper/shadow close/completion alerts

Every immutable `ForwardTradeRecord` can produce one close/completion message containing:

- venue/study/instrument;
- simulated allocation;
- net P&L in dollars and percent;
- fees;
- slippage/cost divergence;
- hold duration;
- exit/completion reason;
- open/close timestamps;
- explicit `PAPER/SHADOW ONLY` wording.

Polymarket uses `TRADE COMPLETED`; held-position venues use `TRADE CLOSED`.

### Idempotency

Trade alert event keys derive from persisted database row IDs. A worker/container restart cannot legitimately create a second alert for the same persisted position/trade. The notification repository also rejects conflicting duplicate payloads.

### Daily heartbeat

Default heartbeat time:

- `18:00 UTC`;
- `19:00 Africa/Lagos`.

Exactly one heartbeat event is keyed per UTC date. It reports active studies, per-study simulated NAV/closed-trade counts, open paper/shadow positions, aggregate simulated NAV, daily completed trades, and a clear `No paper/shadow trades closed today — studies remain active and watching for qualifying setups.` message when appropriate. It points the owner to `/research` for the detailed live readiness/evidence snapshot.

Existing critical/data-integrity and evidence-state-change alerts remain enabled.

Full repository verification for this feature passed in one-time run `33749291095`; temporary verification workflows were removed before merge. Deployment run `33749496652` completed successfully. Settled status run `33749858549` shows `edge-lab-telegram-alerts-1=0` restarts.

## Read-only research snapshot bridge

PR #45 merged as:

`54e19c7b801cac4df94529c1c3692f5bf145977d`

`app/research_snapshot.py` creates a bounded deterministic snapshot combining:

- portfolio paper/shadow NAV/P&L;
- each study's status and evidence recommendation;
- operational readiness;
- incidents;
- recent trades;
- explicit safety flags.

It refuses to run when `SIGNER_ENABLED=true` and contains no credential, wallet, bearer token, arbitrary SQL, shell, or execution capability.

This same snapshot powers Telegram `/research` and can be retrieved manually by ChatGPT through Aurent. No GPT API or automated LLM service is required for this workflow; ChatGPT can request the snapshot when the owner asks for analysis and then reason over the returned evidence.

## ChatGPT → Aurent → VPS typed gateway

Preferred remote-operations architecture:

`ChatGPT → Aurent typed VPS gateway → OVH VPS → Edge Lab`

Aurent repo: `TropicalKenny/aurent-design-intelligence`

Important files:

- `.github/workflows/vps-ops-gateway.yml`;
- `ops/vps-request.json`;
- `scripts/vps/edge-lab-ops.sh`.

Installed VPS runner:

`/usr/local/sbin/aurent-edge-lab-ops`

Current allowlisted operations:

- `status`;
- `research-snapshot`;
- `update`;
- `preflight-baseline`;
- `start-baseline`;
- `restart-baseline`;
- `preflight-full`;
- `start-full`;
- `restart-full`.

The gateway:

- is hard-bound to project `edge-lab`;
- validates operation names before SSH and on the VPS;
- never accepts arbitrary shell commands/arguments;
- uses Aurent's protected SSH secret without copying it into Edge Lab;
- rejects tracked VPS working-tree changes before update;
- uses fast-forward-only Git updates;
- prints provider/Telegram credentials only as SET/MISSING;
- preserves no-wallet/no-signer/no-live-capital boundaries.

For routine Edge Lab remote operations, use this typed gateway rather than asking the owner to enter Termius commands.

## Current credential/configuration state

Last settled typed status, without secret values:

```text
SOLANA_RPC_HTTP_URL=SET
SOLANA_RPC_WS_URL=SET
HELIUS_API_KEY=MISSING
JUPITER_API_KEY=SET
TELEGRAM_BOT_TOKEN=SET
TELEGRAM_CHAT_ID=SET
TELEGRAM_OWNER_USER_ID=SET
signer_enabled=false
```

Do not ask the owner to paste any of those values into chat.

Cloudflare publication remains optional/outstanding; the dashboard is currently local to VPS loopback.

## Current runtime services

Verified running after PR #49 deployment:

- PostgreSQL;
- Redis;
- migrations as required;
- database backup worker;
- internal API on `127.0.0.1:8000`;
- Hyperliquid collector + forward runner;
- Polymarket collector + forward runner;
- Solana launch collector;
- Solana forensic sampler;
- Solana forward runner;
- forward evaluator;
- M6H lifecycle research worker;
- read-only dashboard on `127.0.0.1:8080`;
- private owner-control API on `127.0.0.1:8090`;
- Telegram owner controls;
- Telegram owner alerts with trade lifecycle + daily heartbeat support.

All observed restart counts were `0` in settled run `33749858549`.

## Core `/health` caveat

The legacy internal API `/health` still reports aggregate `healthy=false` because its in-process registry reports `market_data=no-live-collector` and `reconciliation=not-wired`, while the real collectors run as separate containers.

Do not treat that aggregate flag as proof of collector failure. Use each forward runner's readiness/health and `research-snapshot`. Do not modify the legacy endpoint casually; a future health-model change should be scoped and tested.

## Research integrity rules

All continuing research must guard against:

- look-ahead bias;
- survivorship bias;
- final-outcome leakage into decision-time features;
- cherry-picked horizons;
- multiple-testing/strategy overfitting;
- inconsistent fees/slippage/cost assumptions;
- treating hindsight/oracle exits as information that existed at decision time.

Hindsight may be used only as a scoring benchmark after the decision timestamp.

Prefer simple interpretable policies before ML/RL. Contextual bandits/RL remain later-stage research after enough evidence and a proper off-policy evaluation design exists.

## GitHub Actions policy — owner instruction

GitHub Actions is allowed only deliberately.

- Do not use Actions for ordinary coding iterations or unnecessary checks.
- Prefer direct/local verification when available.
- One-time final verification and explicit typed VPS deployment/status operations are justified.
- Remove temporary workflows after use.
- Avoid recurring CI churn and surprise billing.

Recent justified runs include:

- `33746584336` — full repository verification for final Polymarket + Telegram scope fix;
- `33746731801` — deploy final Polymarket/menu fix;
- `33747154288` — one-time exact Telegram scope verification;
- `33747246524` — post-fix read-only research snapshot;
- `33747323362` — settled pre-alert status/restart-count verification;
- `33749291095` — one-time full repository verification for paper trade + heartbeat alerts;
- `33749496652` — deploy PR #49 runtime revision `f454e7f...`;
- `33749858549` — settled post-alert status/restart-count verification;
- `33749917961` — post-alert read-only research snapshot.

## Important continuation files

Read these before making changes:

- `docs/PROJECT_SOURCE.md`;
- `docs/DEPLOYMENT_HANDOFF.md`;
- `docs/OWNER_CONTROLS.md`;
- `docs/MILESTONE6H_LIFECYCLE_RESEARCH.md`;
- `app/research_snapshot.py`;
- `app/notifications.py`;
- `app/workers/owner_alerts.py`;
- `app/dashboard_api.py`;
- `app/telegram_control.py`;
- `app/workers/telegram_controls.py`;
- `app/control_service.py`;
- `app/owner_control_server.py`;
- `app/venues/hyperliquid.py`;
- `app/venues/polymarket.py`;
- `app/solana_forward.py`;
- `app/lifecycle_performance.py`;
- `scripts/verify-repo.sh`.

Aurent continuation files:

- `TropicalKenny/aurent-design-intelligence/.github/workflows/vps-ops-gateway.yml`;
- `TropicalKenny/aurent-design-intelligence/ops/vps-request.json`;
- `TropicalKenny/aurent-design-intelligence/scripts/vps/edge-lab-ops.sh`.

## Exact continuation target

The infrastructure/provider and Telegram-observability blockers are cleared. Do **not** resume by re-fixing Hyperliquid, Polymarket, Helius/Alchemy, Telegram menu, or trade alerts unless fresh evidence shows a regression.

Next work should proceed in parallel with uninterrupted evidence collection:

1. Let the three paper/shadow studies and M6H lifecycle research accumulate real forward evidence.
2. Use Telegram trade-open/trade-close/completion alerts and the 19:00 Lagos heartbeat for passive owner awareness.
3. Use the typed `research-snapshot` operation when the owner asks for progress/review; compare fresh evidence with prior snapshots rather than manually querying unrelated tables.
4. Investigate only fresh hard reasons, warnings, critical incidents, restart-count growth, or data-integrity failures.
5. Once actual trades/execution observations appear, review fees, slippage, drawdown, realized net P&L, sample coverage, and strategy-vs-hold/lifecycle results.
6. Do not relax GREEN evidence gates merely because time has passed. The strongest automated state remains recommendation-only.
7. The next build item is publishing the read-only dashboard behind owner-only Cloudflare Access; after that, add the authenticated browser mutation adapter if the owner wants web control.
8. Keep live trading/signing/fund movement out of scope until a separately authorized micro-live security milestone.
