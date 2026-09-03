# Edge Lab — M6I Owner Controls

M6I adds owner-operated research controls without adding any live-capital capability.

## Runtime placement

Everything operational runs on the Edge Lab VPS:

- PostgreSQL and research journals;
- Hyperliquid/Polymarket/Solana paper-shadow workers;
- M6H lifecycle accounting when enabled;
- read-only dashboard;
- private owner-control service;
- Telegram control worker;
- Telegram alert worker.

Cloudflare is only a future/public gateway for the dashboard. The owner-control API remains loopback-only on the VPS.

## Safety boundary

M6I cannot:

- enable a signer;
- submit an order or swap;
- call Jupiter execution;
- move, bridge, withdraw or transfer funds;
- read wallet/private-key/seed material;
- run shell commands;
- access the Docker socket;
- promote a strategy to live capital;
- delete research evidence.

`SIGNER_ENABLED=false` remains mandatory.

## Shared command engine

The private owner API and Telegram use the same typed `OwnerControlService` and audit table.

Allowlisted mutations:

- `pause` — active study -> paused;
- `resume` — paused study -> active;
- `freeze` — active/paused -> frozen; no ordinary unfreeze command exists;
- `lifecycle_on` / `lifecycle_off` — controls M6H observation only for the frozen Solana M6G study;
- `incident_ack` — records owner acknowledgement without changing evidence;
- `incident_resolve` — resolves an operational incident without deleting it.

Data-integrity incidents are permanent evidence flags and cannot be resolved away by M6I.

Every mutation records:

- idempotency key;
- actor type and actor id;
- command;
- target;
- reason;
- requested/completed timestamps;
- applied/rejected outcome.

## PostgreSQL isolation

The control surfaces use `edge_control`, not the normal `edge` application login and not the `edge_dashboard` read-only login.

`edge_control` receives explicit SELECT grants for the research/performance tables needed by owner views, plus only these existing-table writes:

- `UPDATE (status)` on `forward_studies`;
- `UPDATE (resolved, resolved_at)` on `forward_study_incidents`.

It can insert/update its own M6I settings/cursors and append owner-command audit rows. It receives no DELETE privilege and no all-table write grant.

## Private owner-control API

VPS loopback only:

```text
http://127.0.0.1:8090
```

Endpoints:

```text
GET  /healthz
GET  /v1/summary
GET  /v1/commands
POST /v1/commands
```

The `/v1/*` surface requires the VPS-generated bearer token. The service receives no Telegram token, Helius key, Jupiter key, GoPlus token, forward-ingest secret, wallet material or Docker socket.

## Telegram

The dedicated Edge Lab bot uses outbound Bot API long-polling from the VPS. No Telegram webhook or inbound public port is opened.

A command is accepted only when both match the configured owner identity:

- `TELEGRAM_CHAT_ID`;
- `TELEGRAM_OWNER_USER_ID`.

Read commands:

```text
/help
/status
/balance
/pnl
/performance
/strategies
/evidence
/incidents
```

Control commands:

```text
/pause <solana|polymarket|hyperliquid|all> [reason]
/resume <target> [reason]
/freeze <target> [reason]
/lifecycle on|off [reason]
/incident ack|resolve <incident-id> [reason]
```

`/balance`, `/pnl` and `/performance` always describe simulated paper/shadow research. Live capital remains `$0`.

## Before Helius/Jupiter are added

Edge Lab can run a useful VPS baseline before the Solana provider keys exist.

```sh
sh deploy/start-vps-without-solana-keys.sh
```

That baseline starts:

- PostgreSQL + migrations + backups;
- Hyperliquid collection/forward research;
- Polymarket collection/forward research;
- forward evaluator;
- frozen Solana M6G study registration only;
- read-only dashboard on `127.0.0.1:8080`;
- private owner-control API on `127.0.0.1:8090`;
- Telegram controls;
- Telegram alerts.

It deliberately does not start the Solana network workers.

## Later: enable Solana

After `HELIUS_API_KEY` and `JUPITER_API_KEY` are added to the protected VPS environment, use the normal Solana/full forward preflight and launch path. M6H remains separately owner-toggleable and non-executable.

## Cloudflare

The VPS-local dashboard can be verified before any Cloudflare hostname exists. When the Cloudflare tunnel/Access configuration is ready, publish only the dashboard service (`http://dashboard:8080`), never the internal API or owner-control loopback service.
