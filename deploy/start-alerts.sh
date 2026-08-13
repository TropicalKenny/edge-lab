#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.forward"

[ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN is required}"
: "${TELEGRAM_CHAT_ID:?TELEGRAM_CHAT_ID is required}"

case "$TELEGRAM_BOT_TOKEN" in replace-with-*|example-*|changeme|CHANGE_ME) echo "Refusing example Telegram token." >&2; exit 1 ;; esac
[ "${SIGNER_ENABLED:-false}" = "false" ] || { echo "SIGNER_ENABLED must remain false." >&2; exit 1; }
export SIGNER_ENABLED=false

docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.alerts.yml \
  --profile alerts \
  config -q

docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.alerts.yml \
  --profile alerts \
  up -d --build telegram-alerts

docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.alerts.yml \
  --profile alerts \
  ps telegram-alerts

cat <<'EOF'
Owner alert worker started.
Run a one-time channel test with:
  docker compose --env-file deploy/.env.forward -f docker-compose.yml -f deploy/compose.forward.yml -f deploy/compose.alerts.yml --profile alerts run --rm telegram-alerts python -m app.alert_ops test
EOF
