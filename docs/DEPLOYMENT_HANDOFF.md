# Edge Lab — VPS Forward-Research Handoff

This is the operational handoff for starting Edge Lab's **paper/shadow forward research** on a VPS. It does not enable live trading.

## What is already implemented

- deterministic accounting/risk core;
- realistic paper/shadow execution framework;
- immutable strategy/experiment/forward-study journal;
- RED / AMBER / GREEN-1-candidate evidence evaluator;
- Hyperliquid funding/carry forward runner;
- Polymarket immediate structural forward runner;
- Solana Pump baseline using chain-native discovery and quote-only Jupiter requests;
- daily recommendation-only evaluation;
- local PostgreSQL backups;
- read-only Dashboard V1;
- isolated Cloudflare Tunnel + Access deployment;
- fail-closed deployment preflight/runtime verification;
- fresh Ubuntu VPS provisioning/readiness scripts;
- optional durable Telegram owner alerts for critical/data-integrity incidents and evidence-state changes.

No wallet key, owner-vault credential, live signer, venue order-submission path, bridge transfer, or live-capital authorization belongs in this deployment.

## VPS baseline

Use Ubuntu Server 24.04 LTS or 26.04 LTS with roughly 4 vCPU, 8 GB RAM and 100+ GB NVMe. A GPU is not required.

For a fresh VPS, use `docs/VPS_PROVISIONING.md`. The host preparation flow is:

```sh
bash deploy/provision-ubuntu.sh
bash deploy/check-vps-host.sh
```

The provisioner installs Docker Engine/Compose from Docker's official apt repository and host dependencies only. It never creates application credentials or wallet material.

## External credentials

Required for the core forward-research + hosted dashboard deployment:

1. `HELIUS_API_KEY` — Solana research data only.
2. `JUPITER_API_KEY` — quote-only Swap V2 `/order`; the forward runner has no `/execute` path.
3. `CLOUDFLARE_TUNNEL_TOKEN` — remotely managed Dashboard V1 tunnel.

Optional research enrichment:

- `GOPLUS_ACCESS_TOKEN`.

Optional owner notifications:

- `TELEGRAM_BOT_TOKEN`.
- `TELEGRAM_CHAT_ID`.

Telegram credentials can only send notifications through the owner-alert worker. They are not wallet, signer, venue-order, transfer or withdrawal credentials.

Do **not** provide a Solana/EVM private key, seed phrase/mnemonic, hardware-wallet secret, owner-vault credential or exchange withdrawal key.

## One-time application preparation

```sh
git clone <private-edge-lab-repository-url>
cd edge-lab
sh deploy/init-forward-env.sh
```

The initializer creates mode-600 `deploy/.env.forward`, generates the PostgreSQL password, forward-ingest secret and a **separate dashboard database password**, and never prints them.

Then fill the required external fields:

```text
HELIUS_API_KEY=...
JUPITER_API_KEY=...
CLOUDFLARE_TUNNEL_TOKEN=...
```

Optional:

```text
GOPLUS_ACCESS_TOKEN=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Do not change `SIGNER_ENABLED` to true.

## Cloudflare dashboard setup

Before publishing the hostname:

1. Create a Cloudflare Access Self-hosted application, e.g. `edge.example.com`.
2. Use an owner-only Allow policy and desired MFA/IdP controls.
3. Create a remotely managed Tunnel.
4. Set its Published Application/Public Hostname service URL to **`http://dashboard:8080`**.
5. Never point the public hostname at `api:8000`.
6. Enable **Protect with Access**.
7. Put only the generated tunnel token in the VPS environment.

The Cloudflare-facing `dashboard` service mounts only Dashboard V1 and `/healthz`. It uses the `edge_dashboard` PostgreSQL role with an exact-table SELECT-only allowlist. Future database tables do not automatically become dashboard-readable. The full internal API remains loopback-only at `127.0.0.1:8000`, and cloudflared shares no Docker network with that internal API.

## Mandatory preflight

```sh
sh deploy/preflight-forward.sh
```

It validates secret hygiene, signer lock, Compose rendering, private ports, the dashboard's exact read-only DB identity and the isolated `dashboard_edge` tunnel network. The normal launchers invoke the appropriate preflight automatically as well.

Use `--research-only` only when intentionally validating without Dashboard V1.

Do not bypass a failed preflight.

## Start core research and dashboard

```sh
sh deploy/start-forward.sh
sh deploy/start-dashboard-tunnel.sh
```

Dashboard Internet access can be stopped independently from research collection.

## Optional owner alerts

If you want Telegram alerts, create a Telegram bot through BotFather, contact/start the bot from the owner Telegram account, and determine the owner's chat ID. Put only these notification credentials in `deploy/.env.forward`:

```text
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Then start the isolated alert worker:

```sh
sh deploy/start-alerts.sh
```

The launcher validates that signing remains disabled and prints the exact one-time channel-test command. Run that test immediately and confirm the message arrives.

You can inspect delivery state later with:

```sh
docker compose \
  --env-file deploy/.env.forward \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.alerts.yml \
  --profile alerts \
  run --rm telegram-alerts python -m app.alert_ops status
```

Alert delivery is durable/idempotent with bounded retries. A Telegram outage does **not** change strategy status, contaminate evidence, enable signing, or stop the research engines. Telegram remains optional.

## Verify

```sh
sh deploy/verify-forward.sh --with-dashboard
```

After initial evidence/heartbeats:

```sh
sh deploy/verify-forward.sh --with-dashboard --strict
```

The dashboard verifier tests the exact Cloudflare-facing service, exact database read privileges and runtime Docker network separation, and confirms internal signer/research routes are absent there. Strict verification also requires all three frozen studies to pass their read-only readiness checks.

## First 24 hours

Confirm long-running services remain healthy, no data-integrity incident appears, NAV cadence continues, each venue's paper/shadow evidence reconciles, backups work and can be restored, and the evaluator never mutates strategy status.

If Telegram alerts are enabled, also confirm the alert worker remains healthy and the delivery status does not accumulate `dead` messages.

Only then treat the stored forward clock as operationally trustworthy.

## 90-day programme

Each strategy is independent. Time alone cannot make it GREEN. Evidence must meet the registered cost, drawdown, NAV coverage, sample, execution and integrity gates.

The strongest automated result remains `GREEN-1_CANDIDATE`. It does not activate a signer or move money.

## Real-money boundary

Any micro-live milestone requires a separate security review and explicit owner action. The owner vault remains outside the VPS; deterministic risk stays authoritative; withdrawals remain owner-controlled; AI cannot reveal/import/export wallet keys; GREEN never guarantees profit.
