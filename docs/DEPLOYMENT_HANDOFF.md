# Edge Lab — VPS Forward-Research Handoff

Operational handoff for Edge Lab's **paper/shadow forward research** deployment. This document does not authorize live trading.

Last updated: 3 September 2026, Africa/Lagos.

## Current live deployment

Verified deployed runtime code revision before this docs-only update:

`5f782b6c7cbc144774d9c9ec000b98bbab369c18`

VPS checkout:

`/home/ubuntu/workspace/edge-lab`

Host: OVH Ubuntu VPS, application user `ubuntu`.

Settled typed status run `33747323362` verified:

- Hyperliquid forward runner healthy;
- Polymarket forward runner healthy;
- Solana forward runner healthy;
- PostgreSQL healthy;
- dashboard healthy;
- private owner control healthy;
- all observed container restart counts `0`;
- signer disabled.

Post-fix research snapshot run `33747246524` verified all three studies operationally `ready`, with no hard reasons or warnings and zero permanent data-integrity incidents.

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
- Telegram owner alerts.

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

A live public diagnostic confirmed the latter returns HTTP 200. Runtime revision `5f782b6...` includes the fix and regression coverage.

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

One-time post-deployment API verification run `33747154288` queried all six scopes. Every scope returned the safe 14-command list, with no missing or unexpected commands and `all_scopes_ok=true`.

If Telegram on a phone still shows the old menu after that verified server state, close/reopen the menu/chat/app before changing server code again; that would be local Telegram client cache.

Telegram authorization still requires both the exact configured owner chat and owner user ID. Unauthorized updates are ignored/consumed safely. Telegram has no wallet, signer, shell, or live-capital capability.

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

This lets ChatGPT manually review fresh Edge Lab evidence when the owner asks, without requiring a GPT API key or granting a model autonomous server access.

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

## Current first evidence snapshot

At `2026-09-03T10:59:38Z`:

- three active forward studies;
- independent simulated starting capital: `$1,000` each / `$3,000` aggregate;
- aggregate simulated NAV: `$3,000`;
- aggregate net P&L: `$0`;
- closed trades: `0`;
- execution observations: `0`;
- permanent data-integrity incidents: `0`;
- contaminated studies: `0`;
- Hyperliquid: ready;
- Polymarket: ready;
- Solana: ready.

The six unresolved incidents are historical provider/parser errors and are marked non-data-integrity. Preserve them as audit history unless existing incident-control rules explicitly allow resolution; never delete research history to make a dashboard look cleaner.

## First 24-hour / continuing soak

The infrastructure blocker phase is complete. The next job is evidence accumulation rather than more provider replacement.

During soak, check:

- fresh readiness and NAV cadence;
- restart-count growth;
- new critical or data-integrity incidents;
- actual closed trades/execution observations;
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
- `33746731801` — deploy runtime revision `5f782b6...`;
- `33747154288` — exact six-scope Telegram verification;
- `33747246524` — post-fix research snapshot;
- `33747323362` — settled status and restart counts.

## Continuation checklist for a new chat/agent

1. Read `docs/PROJECT_SOURCE.md` and this file first.
2. Do not assume current `main` equals the deployed runtime SHA; documentation may be ahead.
3. Use Aurent `status` and `research-snapshot` before changing a venue/provider because of historical incidents.
4. Do not reintroduce Helius as a required blocker unless the architecture changes; standard RPC through Alchemy is currently live.
5. Do not reintroduce legacy Telegram live-trading commands.
6. Do not change the frozen M6G entry baseline while studying M6H lifecycle behavior.
7. Do not add live execution/signing/fund movement without a separate explicitly authorized milestone.
8. Continue evidence accumulation and review the first real trades/execution observations when they appear.
