# Edge Lab — Owner Alerts

Owner alerts are an optional observability layer for the paper/shadow research programme. Telegram can notify the owner when:

- a forward study records a critical incident;
- any data-integrity incident is recorded; or
- a strategy's latest evidence recommendation changes (for example AMBER -> RED or AMBER -> GREEN-1_CANDIDATE).

Alerts do **not** trade, sign, transfer funds, change strategy status, resolve incidents, or modify forward evidence. A notification transport failure never contaminates or stops a research study.

## Telegram setup

Create a bot with BotFather, keep its bot token private, and contact/start the bot from the owner account before relying on private-chat notifications. Telegram's Bot API requires a target `chat_id` for `sendMessage`.

Set only on the VPS in uncommitted `deploy/.env.forward`:

```text
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

The token is an alert credential. It must never be reused as a wallet/exchange credential or exposed through Dashboard V1.

## Start

The research stack/database must already be running and migrated.

```sh
sh deploy/start-alerts.sh
```

The worker is in a separate `alerts` Docker profile. It has no public port and receives only the PostgreSQL connection, `SIGNER_ENABLED=false`, and Telegram alert settings. It does not receive Helius, Jupiter, GoPlus, Cloudflare Tunnel, wallet or signer credentials.

## Test the channel

After adding the bot token/chat ID:

```sh
docker compose \
  --env-file deploy/.env.forward \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.alerts.yml \
  --profile alerts \
  run --rm telegram-alerts python -m app.alert_ops test
```

This sends one explicit test message and does not create a research trade/evaluation.

## Delivery semantics

Every alertable event gets a stable database event key. The delivery ledger prevents normal polling from repeatedly sending the same event. Failed sends use bounded exponential retry and become `dead` after the configured maximum attempts; they do not alter research data.

Evidence alerts are emitted only when the latest recommendation differs from the preceding evaluation for that strategy version. `GREEN-1_CANDIDATE` messages explicitly state that the recommendation is evidence only and cannot enable live trading.

## Inspect status

```sh
docker compose \
  --env-file deploy/.env.forward \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.alerts.yml \
  --profile alerts \
  run --rm telegram-alerts python -m app.alert_ops status
```

This reports delivery counts only and never prints the bot token.
