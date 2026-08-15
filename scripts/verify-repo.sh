#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

command -v python >/dev/null 2>&1 || {
  echo "python is required" >&2
  exit 1
}

TMP_DB=$(mktemp /tmp/edge-lab-verify-XXXXXX.db)
trap 'rm -f "$TMP_DB"' EXIT INT TERM

printf '%s\n' '==> pytest'
python -m pytest -q

printf '%s\n' '==> compile'
python -m compileall -q app tests

printf '%s\n' '==> fresh Alembic migration'
DATABASE_URL="sqlite:///$TMP_DB" python -m alembic upgrade head >/dev/null

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  printf '%s\n' '==> full Docker Compose render'
  POSTGRES_PASSWORD=verify-postgres-password-long-enough \
  FORWARD_INGEST_SECRET=verify-forward-ingest-secret-long-enough \
  DASHBOARD_DB_PASSWORD=verify_dashboard_password_long_enough \
  CLOUDFLARE_TUNNEL_TOKEN=verify-tunnel-token \
  HELIUS_API_KEY=verify-helius \
  JUPITER_API_KEY=verify-jupiter \
  TELEGRAM_BOT_TOKEN=verify-telegram-token \
  TELEGRAM_CHAT_ID=123456 \
  SIGNER_ENABLED=false \
  docker compose \
    -f docker-compose.yml \
    -f deploy/compose.forward.yml \
    -f deploy/compose.solana-forward.yml \
    -f deploy/compose.lifecycle.yml \
    -f deploy/compose.dashboard-tunnel.yml \
    -f deploy/compose.alerts.yml \
    --profile forward \
    --profile solana \
    --profile lifecycle \
    --profile dashboard \
    --profile alerts \
    config >/dev/null
else
  printf '%s\n' 'SKIP: Docker Compose unavailable; Python/migration checks passed.'
fi

printf '%s\n' 'VERIFIED: local Edge Lab repository checks passed.'
