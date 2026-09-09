# Edge Lab — VPS Forward-Research Handoff

Operational handoff for Edge Lab's **paper/shadow forward research** deployment. This document does not authorize live trading.

Last updated: 8 September 2026, Africa/Lagos.

## Current live deployment

Verified deployed runtime code revision:

`8b134d2d97fbb0190b60731af5632af5c8d88671`

PR #59 execution-price precision repair, following PR #58 paper-research reliability repair. Earlier research and Telegram paper/shadow alerts remain included. See the 6 September verification at the end of this document.

VPS checkout:

`/home/ubuntu/workspace/edge-lab`

Host: OVH Ubuntu VPS, application user `ubuntu`.

Settled typed status run `33749858549` verified:

- deployed SHA `f454e7fb64eb117278fcc8f1def1153d896cf39e`;
- Hyperliquid forward runner healthy;
- Polymarket forward runner healthy;
- Solana forward runner healthy;
- PostgreSQL healthy;
- dashboard healthy;
- private owner control healthy;
- Telegram controls running with restart count `0`;
- Telegram alerts running with restart count `0`;
- all observed container restart counts `0`;
- signer disabled.

Post-alert research snapshot run `33749917961`, captured at `2026-09-03T11:29:11Z`, verified all three studies operationally `ready`, with no hard reasons or warnings and zero permanent data-integrity incidents. At that capture there were still zero open positions, zero closed trades, zero execution observations, `$3,000` aggregate simulated NAV and `$0` net P&L.

<!-- M6K_DEPLOYED_2026_09_05 -->
### M6K production research deployment — 5 September 2026

The full research stack was updated, preflighted, rebuilt, restarted, and reverified at `957d456e8a70d7ec13984bd350cfd94961dc7820` through the Aurent typed VPS gateway. M6K is observation-only and runs inside the existing M6J research worker services, writing separate `m6k-hl`, `m6k-pm`, and `m6k-sol` telemetry.

Operational run chain:

- M6K CI `33974524827` — success;
- pre-deploy status `33974567822` — success;
- VPS fast-forward update `33974625579` — success;
- full preflight `33974710976` — success;
- full restart `33974762226` — success;
- settled post-deploy status `33974939606` — success;
- read-only research snapshot `33974974828` — success.

Settled status showed the three forward runners healthy, the dashboard and owner-control surfaces healthy, all observed container restart counts at `0`, the safe Telegram menu unchanged, and `signer_enabled=false`. The three M6J research containers that now carry M6K logic were all up with zero restarts and no public ports.

The first post-restart snapshot showed all frozen forward studies operationally `ready`. `m6k-hl` was already collecting and screened four coin/horizon pairs (one screen pass, three rejects); `m6k-sol` had begun cycling but had not yet seen a new UNKNOWN record; `m6k-pm` had not yet durably recorded its first eligible event-consistency observation in the short post-restart window. These are research collection states, not trading/promotional states.

The safety object remained fully fail-closed: no live trading, signing, fund movement, wallet access, or shell access, with live capital `$0`.

Detailed M6K rules are in `docs/MILESTONE6K.md`.

## Current safety boundary

This deployment is research-only.

It has no authorized live-capital path, no wallet key, no owner-vault credential, no live signer, no venue order-submission authority, no bridge/transfer/withdrawal authority, and no Jupiter `/execute` path.

`SIGNER_ENABLED=false` is mandatory.

Do **not** provide a Solana/EVM private key, seed phrase, mnemonic, hardware-wallet secret, owner-vault credential, exchange withdrawal key, or any other signing/fund-movement credential to this VPS or to chat.

A future micro-live milestone requires a separate security review and explicit owner action.

## What is running

The full current paper/shadow stack includes:

- PostgreSQL;
- Redis;
- migrations;
- database backups;
- internal API on `127.0.0.1:8000`;
- Hyperliquid market collector + funding/carry forward runner;
- Polymarket collector + immediate structural forward runner;
- Solana launch collector;
- Solana forensic sampler;
- Solana Pump M6G forward runner;
- forward evidence evaluator;
- M6H lifecycle research worker;
- read-only Dashboard V1 on `127.0.0.1:8080`;
- private owner-control API on `127.0.0.1:8090`;
- Telegram owner controls;
- Telegram owner alerts, including paper/shadow trade lifecycle notifications and daily heartbeat.

No GPU is required.

## Provider/configuration state

Last verified without exposing secret values:

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

The standard Solana RPC HTTP/WebSocket path is active and currently backed by Alchemy. Helius is missing but is **not** a deployment blocker because the full Solana research stack is already running through the standard RPC path.

Jupiter remains quote-only for the frozen Solana research baseline. Do not add `/execute` or a wallet/taker address.

Cloudflare publication remains optional/outstanding. The dashboard is currently loopback-only.

## Fresh VPS preparation

For a fresh Ubuntu VPS, use `docs/VPS_PROVISIONING.md`.

Typical host setup remains:

```sh
bash deploy/provision-ubuntu.sh
bash deploy/check-vps-host.sh
```

Then clone the private repository and initialize the local environment file:

```sh
sh deploy/init-forward-env.sh
```

The initializer creates internal credentials locally and must not print them. Preserve mode `600` on `deploy/.env.forward`.

Fill external provider values directly on the VPS. Never paste their values into chat.

## Preflight and launch

The research preflight remains mandatory:

```sh
sh deploy/preflight-forward.sh
```

Do not bypass a failed preflight.

The normal full launcher starts the current research services while forcing signing off. The current operationally preferred remote path is the Aurent typed gateway rather than manual Termius commands.

Aurent allowlisted operations are:

- `status`;
- `research-snapshot`;
- `update`;
- `preflight-baseline`;
- `start-baseline`;
- `restart-baseline`;
- `preflight-full`;
- `start-full`;
- `restart-full`.

Architecture:

`ChatGPT → Aurent typed VPS gateway → OVH VPS → Edge Lab`

The gateway is hard-bound to Edge Lab operations and does not expose arbitrary shell access.

## Current venue notes

### Hyperliquid

Current state: `ready`, Docker health `healthy`.

The current public response contract for `spotMetaAndAssetCtxs` is indexed rather than equal-length positional pairing. For each listed market, use its explicit market index to select the matching context row.

Historical parser errors remain in the incident journal as non-data-integrity history. Do not treat those old rows as a current outage while fresh readiness is `ready`.

### Polymarket

Current state: `ready`, Docker health `healthy`.

Gamma's `/markets/keyset` ordering contract changed. The old request:

`order=liquidity_num`

returns HTTP 422. Edge Lab now uses:

`order=liquidityNum`

A live public diagnostic confirmed the latter returns HTTP 200.

The current M6F research action is immediate/completion-style. Telegram therefore reports a persisted Polymarket trade record as a `PAPER/SHADOW TRADE COMPLETED` event rather than fabricating a durable open-position alert.

### Solana M6G

Current state: `ready`, Docker health `healthy`.

The entry baseline remains frozen. Standard Solana RPC HTTP/WebSocket collection is active. Jupiter is quote-only. No signing or transaction submission exists in the current milestone.

### M6H lifecycle research

The lifecycle worker is running independently of the frozen M6G entry baseline. Its policies remain hypothetical/non-executable.

## Telegram owner controls

The current persisted owner menu is:

```text
/research
/status
/performance
/evidence
/strategies
/balance
/pnl
/incidents
/pause
/resume
/freeze
/lifecycle
/incident
/help
```

`/research` returns the consolidated read-only research snapshot.

The owner previously saw a stale legacy Kennysbot menu containing live-oriented commands such as `/sell`, `/sellall`, `/golive`, `/tp`, `/sl`, `/pending`, `/approve`, and `/reject`.

The final fix writes the safe menu to six Telegram command variants at worker startup:

- default, generic language;
- default, English;
- all private chats, generic;
- all private chats, English;
- exact owner chat, generic;
- exact owner chat, English.

One-time post-deployment API verification run `33747154288` queried all six scopes. Every scope returned the safe 14-command list, with no missing or unexpected commands and `all_scopes_ok=true`. Settled status run `33749858549` again reported `telegram_menu_ok=true`.

If Telegram on a phone still shows the old menu after that verified server state, close/reopen the menu/chat/app before changing server code again; that would be local Telegram client cache.

Telegram authorization still requires both the exact configured owner chat and owner user ID. Unauthorized updates are ignored/consumed safely. Telegram has no wallet, signer, shell, or live-capital capability.

## Telegram paper/shadow activity alerts

PR #49 adds owner awareness without adding trading authority.

### Open notifications

Hyperliquid durable position rows and accepted Solana M6G entries generate one Telegram `PAPER/SHADOW TRADE OPENED` event after the research state has been persisted.

The alert includes, as applicable:

- venue;
- study;
- asset/instrument;
- simulated allocation;
- shadow/entry prices;
- fees where available;
- opening timestamp;
- planned hold/close time;
- a clear paper/shadow/no-real-money warning.

Rejected Solana entries do not alert.

### Close/completion notifications

Each immutable `ForwardTradeRecord` can generate exactly one Telegram close/completion event containing:

- venue/study/instrument;
- simulated allocation;
- net P&L in dollars and percent;
- fees;
- slippage/cost divergence;
- hold duration;
- exit/completion reason;
- opened/closed timestamps;
- `PAPER/SHADOW ONLY` warning.

Hyperliquid/Solana held-position events use `TRADE CLOSED`; Polymarket's immediate structure uses `TRADE COMPLETED`.

### Idempotency/restarts

Event keys are derived from persisted position/execution/trade IDs. The notification table has a unique `(channel, event_key)` constraint and rejects conflicting duplicate payloads. Restarting the Telegram alert worker does not legitimately resend the same persisted trade event.

### Daily heartbeat

Default configuration:

`TELEGRAM_HEARTBEAT_HOUR_UTC=18`

This means approximately **19:00 Africa/Lagos**.

There is at most one `daily-heartbeat:YYYY-MM-DD` event per UTC date. The heartbeat reports:

- active studies;
- per-study simulated NAV and closed-trade count;
- currently open paper/shadow positions;
- combined simulated NAV;
- number of trades completed that UTC day;
- a no-trade-but-still-watching statement when no trade completed;
- instruction to use `/research` for the detailed readiness/evidence snapshot.

Existing critical/data-integrity and evidence-state alerts remain active.

Feature verification: one-time run `33749291095` passed the full repository verifier. Temporary verification workflows were removed. Deployment run `33749496652` completed successfully. Settled status run `33749858549` verified `edge-lab-telegram-alerts-1=0` restarts.

## Research snapshot for ChatGPT/manual review

`python -m app.research_snapshot` exposes a bounded deterministic JSON snapshot from a read-only database identity.

It includes:

- simulated portfolio NAV/P&L;
- each study's state;
- operational readiness;
- evidence recommendation;
- incidents;
- recent trades;
- explicit safety flags.

It refuses to run if signing is enabled.

Aurent's typed `research-snapshot` operation runs the snapshot inside the dashboard service using the `edge_dashboard` read-only database identity.

This lets ChatGPT manually review fresh Edge Lab evidence when the owner asks, without requiring a GPT API key or granting a model autonomous unrestricted server access.

## Dashboard and future Cloudflare publication

The current dashboard is local on:

`127.0.0.1:8080`

When the owner chooses to publish it:

1. create a Cloudflare Access self-hosted application;
2. create a remotely managed Cloudflare Tunnel;
3. point its service URL to **`http://dashboard:8080`**;
4. never publish the internal API at port 8000;
5. protect the hostname with owner-only Cloudflare Access;
6. keep the dashboard DB identity `edge_dashboard` read-only.

The future browser mutation adapter must validate Cloudflare Access identity and CSRF server-side, then proxy only typed owner-control commands. Never expose the private owner-control bearer token to browser JavaScript and never expose `127.0.0.1:8090` directly to the public Internet.

This Cloudflare-protected dashboard is the next build item while the research stack continues accumulating evidence.

## Verification commands/reference

Repository verification still includes the deployment handoff contract and should remain green.

For the full dashboard-aware verifier:

```sh
sh deploy/verify-forward.sh --with-dashboard --strict
```

Do not weaken strict readiness merely to make verification pass.

The legacy internal `/health` aggregate may show `healthy=false` because its in-process registry reports `market_data=no-live-collector` and `reconciliation=not-wired` while collectors actually run as separate containers. Use per-runner health/readiness and `research-snapshot` for current operational truth. Change that legacy health model only in a separately scoped/tested task.

## Evidence and promotion boundary

The evaluator is recommendation-only. Time passing is not enough for promotion.

The strongest automated research result remains `GREEN-1_CANDIDATE`; it **does not activate a signer or move money**.

Evidence must still satisfy the registered sample, cost/slippage, drawdown, NAV-coverage, execution-observation, and data-integrity gates.

Guard all research against look-ahead bias, survivorship bias, outcome leakage, cherry-picked horizons, multiple-testing overfit, and inconsistent cost assumptions.

## Current evidence snapshot

At `2026-09-03T11:29:11Z`:

- three active forward studies;
- independent simulated starting capital: `$1,000` each / `$3,000` aggregate;
- aggregate simulated NAV: `$3,000`;
- aggregate net P&L: `$0`;
- closed trades: `0`;
- execution observations: `0`;
- permanent data-integrity incidents: `0`;
- contaminated studies: `0`;
- Hyperliquid: ready, open positions `0`;
- Polymarket: ready;
- Solana: ready, open positions `0`.

The six unresolved incidents are historical provider/parser errors and are marked non-data-integrity. Preserve them as audit history unless existing incident-control rules explicitly allow resolution; never delete research history to make a dashboard look cleaner.

## First 24-hour / continuing soak

The infrastructure and owner-observability blocker phase is complete. The next job is evidence accumulation rather than more provider replacement.

During soak, check:

- fresh readiness and NAV cadence;
- restart-count growth;
- new critical or data-integrity incidents;
- actual open/closed trades and execution observations;
- Telegram trade-open/trade-close delivery;
- daily 19:00 Lagos heartbeat delivery;
- fees and slippage;
- realized/stressed net P&L;
- drawdown;
- Hyperliquid funding/carry behavior;
- Polymarket structural opportunity coverage;
- Solana launch baseline behavior;
- M6H policy performance versus hold/baseline;
- backup continuity.

Use the typed `research-snapshot` for owner-requested reviews and compare snapshots over time.

## GitHub Actions policy

Use GitHub Actions deliberately only where the remote run itself is justified, such as a one-time final verification or typed VPS deployment/status operation. Do not create persistent workflows for routine coding/exploration. Remove temporary workflows after use.

Recent justified operational runs:

- `33746584336` — full repository verification for final Polymarket/Telegram fix;
- `33746731801` — deploy final Polymarket/menu fix;
- `33747154288` — exact six-scope Telegram verification;
- `33747246524` — post-fix research snapshot;
- `33747323362` — settled pre-alert status and restart counts;
- `33749291095` — full repository verification for Telegram paper trade/heartbeat alerts;
- `33749496652` — deploy runtime revision `f454e7f...`;
- `33749858549` — settled post-alert status and restart counts;
- `33749917961` — post-alert research snapshot.

## Continuation checklist for a new chat/agent

1. Read `docs/PROJECT_SOURCE.md` and this file first.
2. Do not assume current `main` equals the deployed runtime SHA; documentation may be ahead.
3. Use Aurent `status` and `research-snapshot` before changing a venue/provider because of historical incidents.
4. Do not reintroduce Helius as a required blocker unless the architecture changes; standard RPC through Alchemy is currently live.
5. Do not reintroduce legacy Telegram live-trading commands.
6. Preserve the PR #49 trade-alert idempotency and paper/shadow-only wording.
7. Do not change the frozen M6G entry baseline while studying M6H lifecycle behavior.
8. Do not add live execution/signing/fund movement without a separate explicitly authorized milestone.
9. Continue evidence accumulation and review the first real trades/execution observations when they appear.
10. Next build: publish the read-only dashboard behind owner-only Cloudflare Access, then add a typed authenticated browser mutation adapter only if requested.

## Reliability repair — 6 September 2026

Owner authorized autonomous paper-research repairs and deployment. Live signing and real capital remain disabled.

Pre-repair live verification: Aurent runs `34008504040` (research snapshot, 03:14 UTC) and `34008533960` (runtime status). VPS/main revision `73c7166b72f1f9595472a98c84ebb548e16f2138`. Five active studies; exploratory M6L-v1 had five closed losses, realized P&L -54.6717262635 USD and marked NAV 944.2970473692 USD. These results must remain visible.

Implemented repair:

- Stable incident retry identity and first-observation timestamps; NAV quote errors cannot produce conflicting timestamp retries.
- Mandatory momentum and available volume-acceleration checks now match the written alpha contract.
- New `m6l-v2` strict/exploratory studies separate corrected entries from historical v1 evidence. Existing v1 studies accept no new entries, retain their original exits, and complete only after positions are reconciled/closed. No historical loss or journal row is deleted or reclassified.
- All M6L cohort exits and NAV checks run before candidate enrichment; candidate scans have a ten-second between-candidate budget. M6L worker polling sleep is capped at 15 seconds. This is not a guaranteed 15-second execution latency: provider requests and sequential positions still take time.
- V2 full-size quote-valid exits may record adverse price impact up to 100%; the 8% entry impact gate remains. This avoids confusing an expensive executable exit with no route. Stops remain triggers, not guaranteed fills. No-route deadline losses remain zero recovery.
- Executable mark telemetry is separate from candidate counts and keyed by actual quote timestamp.
- Evaluation records carry study identity; the daily scheduler and dashboard no longer confuse same-version, same-start cohorts. Ambiguous old evaluations are not guessed.
- Lifetime drawdown uses the entire NAV history; chart output stays limited to 60 points. Existing fraction units remain compatible and are explicitly labeled. Realized/total/unrealized P&L and NAV timestamps are exposed separately.
- Unresolved incident count uses all rows rather than the 20-row display cap.
- M6L reports use the same journal/config/NAV/integrity health checks as other Solana studies. UI identifies cohorts and evaluations with newer trades.

Validation: all 260 tests passed, including nine new regression tests; Python compilation, shell syntax, and fresh Alembic migration passed. GitHub CI run 34009191597 also passed, including Compose rendering. The initial repair introduced no schema change; the precision follow-up below adds a widening-only migration.

Research decision: prioritize correctness and versioned forward evidence over adding more strategies. Jupiter documentation confirms quote-only pricing without a taker is supported, but a quote is still not an executed transaction: https://dev.jup.ag/docs/guides/how-to-build-a-swap-with-ultra . No profitability claim follows from quote simulations. Polymarket synchronized-book acquisition remains a separate research task; its stale-book rejection counts are not a reason to force simulated trades.

Outstanding beyond this repair: verified external dashboard/OTP journey, email-provider configuration (missing in inspected Edge Lab environment), backup restore drill, and sustained forward results from v2. Do not describe the whole product as finished or profitable.

Deployment: PR #58 merged as `8709b84fc965bc1df33fb5a42ca90eb9122cd13a`; Aurent restart-full run `34024624340` succeeded. Post-deploy status `34024737296` verified healthy services, zero restarts, safe Telegram menu and signing disabled. Snapshot `34024743220` at 09:28 UTC showed both v2 cohorts collecting independently. Historical v1 exploratory had nine closed trades, no open positions and realized P&L -57.7828647045 USD; its history is retained.

Live verification exposed a legacy execution-price precision fault: NUMERIC(28,10) rounded tiny USD-per-atomic-token prices to zero and blocked evaluation/finalization. The follow-up widens only the two execution price columns to NUMERIC(50,30). Old zero-valued records remain unchanged; evaluation reconstructs a price only from that row's immutable decision-time quote when its positive price demonstrably rounds below the old precision. Unexplained zero prices still fail closed. No current market prices or fabricated fills are substituted. Migration downgrade refuses destructive precision reduction. PR #59 merged as `8b134d2d97fbb0190b60731af5632af5c8d88671`; all 262 tests, compilation, shell checks, migration and CI Compose rendering passed (CI `34025055573`). Aurent full deployment `34025112177` and status `34025246504` passed, with four forward runners healthy, zero restarts, healthy private dashboard/control and signing disabled.

Fresh snapshot `34051760242`, captured 2026-09-06 18:27:24 UTC, confirms both v1 studies completed and both v2 studies active/ready with separate evaluations. V1 exploratory final loss: -57.7828647045 USD across nine closed trades. V2 exploratory: six closed trades, -8.4609630932 USD, NAV 991.5390369068 USD, zero open positions and zero incidents. V2 strict: zero trades, NAV 1000 USD, zero incidents. Both had 542 scans since launch. Daily evaluations predate the later v2 trades; the dashboard correctly flags newer trades. Historical non-integrity incidents remain recorded; none is a new v2 incident. The old completed studies being reported STUDY_NOT_ACTIVE/NAV_STALE reflects retirement, not a failed active collector.

The seven independent 1000 USD study books sum to 7000 USD nominal research capital. This is not one funded account and must not be sold as portfolio profitability. No live funds exist. The legacy internal API health registry still reports no-live-collector/not-wired while actual separate collectors are fresh; full external dashboard OTP and backup restore verification remain outstanding.

Owner requested deep strategy research after the deployment. Research will compare carry, executable prediction-market arbitrage, momentum, cost attribution, combination rules and out-of-sample validation before proposing further strategy changes.


## Strategy research continuation — 8 September 2026

Deep strategy research is recorded in `docs/research/report-source.md`, with the verified raw paper snapshot in `docs/research/snapshot-20260908.json`. Aurent snapshot run `34292437379` captured 23:51:04 UTC: v2 exploratory 30 closed trades, realized P&L -64.5386369829 USD, NAV 935.4613630171 USD, no open positions; strict v2 zero trades. The latest ten v2 trades lost 17.2402372972 USD, including recorded quote-deterioration/slippage of 12.3423891545 USD on 249.9726442807 USD combined allocations. These numbers supersede the earlier six-trade snapshot. There are three v2 historical NAV quote-unavailable incidents, none a permanent data-integrity incident. All five active studies report ready and have fresh observations.

Research decision: accounting/cost diagnostics first, then versioned longer-horizon carry and simple liquid-asset momentum challengers, followed by synchronized event-level Polymarket simulation. Keep current v2 evidence intact and do not increase meme exposure or silently retune the study. The report distinguishes historical strategy evidence, current venue mechanics and untested implementation hypotheses. No new challenger, portfolio weights, pause or live capability has been deployed in this research phase. Current code revision remains 8b134d2d97fbb0190b60731af5632af5c8d88671; documentation may be newer.

Carry baseline inspection: default 24-hour holding horizon versus 31 bps round-trip fee/slippage budget can explain an empty opportunity set at modest funding; existing M6J 7/14/30-day research must be evaluated using realized funding and total capital. Polymarket's 112 positive event checks in the last day are not fills; synchronized books, current per-market fees and multi-leg failure modeling remain prerequisites. Security UNKNOWN remains a data gap, not evidence a token is safe. Public OTP/email and backup restore verification remain outstanding.


## Cost reconciliation implementation — 9 September 2026

Owner reconfirmed autonomous paper research. GitHub/Aurent access is available; no new connection was required. Before-change snapshot run 34331000076 (08:47 UTC) showed v2 exploratory 32 closed trades and -67.7269194894 USD realized P&L, with no open position. It remains unprofitable.

Added a read-only per-study cost audit to research snapshots. It aggregates every closed trade through capture time, not the recent-ten display, and reports gross/net P&L, recorded fees/slippage, allocation-relative cost bps and accounting-identity failures. For supported Solana records it joins immutable exit metadata in batches, scopes joins to study and capture time, and compares exit quote USD proceeds minus entry quote USD expenditure with recorded net. It explicitly counts missing/invalid evidence and reports reconciled-subset coverage. Favorable quote-value differences clamped by the historical cost formula can create differences; these are diagnostics, not permission to rewrite history or declare profits. Network costs and settlement remain unverified. No schema, position size, strategy parameters or signing changes.

Next: use the deployed audit to measure discrepancies before registering corrected versioned accounting or longer-horizon carry and liquid trend challengers. No new challenger has been deployed by this change. Tests cover favorable quotes, full-loss handling, invalid numbers, 205-record batching, study isolation, future cutoff, missing evidence and empty studies. Deployment/verification evidence is in the associated PR and Aurent run history.


Live cost audit verified 9 September 2026 at 08:53:36 UTC after PR #61 (`8007c10ebafa4402f15fa0cf388be4922a29108c`). CI 34331386106 passed. Aurent dashboard deployment 34331473213 succeeded and verified read-only health; research snapshot 34331608604 succeeded using the read-only database role. Trading workers retain the prior strategy code/configuration; this selective deployment updates the dashboard snapshot reader only.

All 32 v2 exploratory trades reconciled, zero missing/invalid records, zero gross-minus-cost journal identity failures. Gross recorded P&L -28.8050882187 USD; recorded quote-deterioration/slippage 38.9218312707 USD; net -67.7269194894 USD on 799.9314202148 USD summed entry allocations (486.56 bps recorded cost). Five trades differ under quote cash-flow arithmetic, improving aggregate P&L by only 2.7652756087 USD to -64.9616438807 USD. All nine old v1 trades also reconciled; quote cash-flow P&L -54.7799280602 USD versus recorded -57.7828647045 USD. Historical records are unchanged. Neither arithmetic supports profitability. Quoted USD values still do not verify actual settlement/network costs. All five active studies remain ready; old v1 studies are completed. Next priority remains new longer-horizon carry and liquid-trend experiments, with preregistered rules and unseen-data evaluation.


## Revised research decision — 9 September 2026

See `docs/research/decision-plan-20260909.md` for the new cited decision report. Following the full cost audit, recommend implementing a simple daily BTC/ETH spot long/cash trend experiment first, then a versioned 14-day carry study with a seven-day comparison. This changes implementation order from the earlier carry-first report because trend is simpler to validate and both existing carry config paths cap holdings at 72 hours. Carry remains a hypothesis, not a promised yield.

Proposed trend primary: 90-day moving average, 180-day comparison, separate fixed initial BTC/ETH sleeves, cash/buy-and-hold benchmarks, post-signal fills and full costs. Parameters are preregistered engineering choices, not demonstrated optima. Select and verify the actual venue/asset/history before performance testing; Hyperliquid BTC spot can be UBTC, and its candle API retains only 5,000 candles per interval. No silently substituted history.

Stop routine tuning of the current meme strategy; retain history and its unchanged low-cost benchmark where useful. Defer Polymarket baskets until synchronization, conversion and stranded-leg costs are modeled. Defer learned allocation/AI forecasting and portfolio combination until individual evidence qualifies. Limit the first cycle to baseline, one challenger and robustness; negative findings are valid stopping outcomes. No strategy deployment, pause, spending or live capability was changed during this research turn.


## M6N implementation — 9 September 2026

Owner approved the trend-first research decision. Added the locked BTC-USD/ETH-USD Coinbase replay and durable daily signal observation worker; exact rules and limitations are in `docs/research/trend-protocol-20260909.md` and `app/trend_protocol.json`. Historical windows, 90/180-day rules, 60+5 bps per-side cost assumptions, delayed fills, cash/buy-hold and fixed robustness scenarios were defined before performance retrieval. Historical replay is never counted as forward portfolio P&L. No optimization, automatic promotion, orders or new credentials.

Deployment uses the existing typed restart-dashboard-local operation. Its compose now starts the independent public-data trend worker and mounts the research summary read-only into the dashboard snapshot. Named volume `edge-lab-trend-research-v1` stores immutable raw candles, protocol hash, replay and idempotent actual-time daily observations. Missing/revised/nonfinite data blocks the replay; stale/invalid summaries are explicit. This SQLite research volume is outside the PostgreSQL backup job; restore verification is outstanding. Other readers without the mount explicitly report unavailable. Existing trading studies are unchanged.

Local verification: existing 264 tests plus 12 new trend tests pass (276 total after final targeted test addition). Tests cover cost reconciliation, delay/lookahead, bad coverage, restart idempotency, missing provider data, protocol drift and summary freshness. The local network request timed out, so no performance conclusion or successful VPS data retrieval is claimed before deployment verification. Fourteen-day carry and executable-quote forward trend books remain subsequent implementation work; observation-only does not demonstrate profitability.


## M6N deployed results — 9 September 2026, 14:09 UTC

PR #62 merged as `8fef13c5e6b68de16ee6966f38fbd8bef3581827`. CI `34361413164` passed tests, compilation, migration and both Compose renders. Pre-deploy status `34361411454` confirmed expected VPS source, healthy existing workers and signing disabled. Typed dashboard/research deployment `34361594891` succeeded. Read-only snapshot `34361763447` at 14:09:47 UTC verified trend status observing, not stale, one daily observation and zero forward trades. The VPS retrieved complete required Coinbase history and froze the report. Results are preserved in `docs/research/trend-results-20260909.json`.

Holdout (2025-01-01 through 2026-08-31), per independent 1000 USD simulated book: 90-day primary +228.7252 USD (+22.8725%), maximum drawdown 36.2089%, 23 round trips; 180-day comparison -226.9051 USD (-22.6905%), drawdown 36.3027%; buy-and-hold -219.0057 USD (-21.9006%), drawdown 60.0403%; cash zero. Primary doubled-cost P&L falls to +52.2702 USD; one additional day of delay gives +51.9991 USD. Subtracting the primary's largest winning trade contribution leaves -99.7409 USD. This subtraction is attribution, not path resimulation.

The primary also lagged buy-and-hold in development (+111.24% versus +472.78%) and validation (+42.30% versus +316.22%). Its validation drawdown was 50.08% versus 34.11% for buy-and-hold. Positive holdout profit is therefore not sufficient evidence of a robust or subscription-paying strategy. Decision: no promotion to a forward execution book, no parameter search based on this now-seen holdout, continue the frozen daily observation record. The 180-day rule is not advanced. Next research implementation remains separately versioned 14-day carry with the seven-day comparison and full realized-funding/capital accounting. There is still no proven profitable live or forward paper strategy.

Selective deployment changed the dashboard reader and started the independent trend worker; existing trading worker processes retain their previous strategy revision. The top-of-file older runtime revision describes those trading workers, not the new trend/dashboard image. All snapshot safety flags remain false and live capital remains zero.


## M6O carry implementation — 9 September 2026

Implemented the approved separate 14-day carry hypothesis with one seven-day comparison. See `docs/research/carry-protocol-20260909.md` and `app/carry_protocol.json`. Existing 72-hour runners/studies and M6N trend rules remain frozen. New public-data worker explicitly hedges UBTC/USDC spot with BTC perpetual, pins token identity, uses minimum complete 7/30-day trailing funding averages, full depth, two-sided fees and adverse reserves, and sizes independent 1000 USD books with roughly 40% spot/40% short collateral/20% reserve.

This is conditional quote shadow research, not proven executable trading. Actual hourly funding rates use prior sampled oracle proxies, not exact settlement. It reports full-book return, basis P&L, doubled costs and failed-leg unwind plus 100 bps stress. Missing rates/oracles cannot become zero income; unpriceable exits remain open with unknown NAV; overdue data or monitoring gaps contaminate and freeze further entries. Transactional SQLite prevents duplicate entry/close accounting across restarts. Margin/loss guards are not guaranteed stop prices or exact liquidation simulation. Wrapper/stablecoin failures, queue fills and settlement are not modeled; no automatic promotion is allowed.

Deployment adds the independent carry worker and read-only snapshot field through the existing dashboard gateway. No credentials, public ports or PostgreSQL grants. The named research volume is outside PostgreSQL backup coverage. Sixteen new tests cover accounting, negative funding, oracle timing, missing hours, bad books, identity drift, restart idempotency, collateral reservation, monitoring gaps, margin exits and unknown exit valuation. Deployment verification and first live decisions must be recorded after the gateway completes; no profitable outcome is claimed at implementation time.


M6O initial deployment verification: PR #63 merged as b7be828e6db1e04998fb2b2d2d18c145361cc9cb; CI 34363426021 and deployment 34363559148 passed. First snapshot 34363756689 at 14:27:59 UTC correctly reported blocked with `funding hour misaligned`; no carry entry was opened. The new validator incorrectly required timestamps to equal exact UTC hour boundaries. Corrective implementation preserves actual venue millisecond timestamps, validates one event per hour and full expected coverage, rejects conflicts, and respects actual event time at position entry/exit. Forecasts still use the same 7/30-day averages, five-minute buffer and unchanged thresholds. Two additional regressions cover timestamp offsets, boundary eligibility and duplicate hour conflicts. This is a data-contract correction, not strategy optimization.
