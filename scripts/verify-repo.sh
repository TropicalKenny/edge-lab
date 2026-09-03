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

printf '%s\n' '==> shell syntax'
for script in \
  deploy/preflight-core-forward.sh \
  deploy/start-core-forward.sh \
  deploy/preflight-controls.sh \
  deploy/start-control-plane.sh \
  deploy/start-dashboard-local.sh \
  deploy/start-vps-without-solana-keys.sh; do
  sh -n "$script"
done

printf '%s\n' '==> fresh Alembic migration'
DATABASE_URL="sqlite:///$TMP_DB" python -m alembic upgrade head >/dev/null

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  printf '%s\n' '==> full Docker Compose render'
  POSTGRES_PASSWORD=verify-postgres-password-long-enough \
  FORWARD_INGEST_SECRET=verify-forward-ingest-secret-long-enough \
  CONTROL_DB_PASSWORD=verify_control_password_long_enough \
  OWNER_CONTROL_API_TOKEN=verify_owner_control_token_long_enough_123456 \
  DASHBOARD_DB_PASSWORD=verify_dashboard_password_long_enough \
  CLOUDFLARE_TUNNEL_TOKEN=verify-tunnel-token \
  HELIUS_API_KEY=verify-helius \
  JUPITER_API_KEY=verify-jupiter \
  TELEGRAM_BOT_TOKEN=verify-telegram-token \
  TELEGRAM_CHAT_ID=123456 \
  TELEGRAM_OWNER_USER_ID=123456 \
  SIGNER_ENABLED=false \
  docker compose \
    -f docker-compose.yml \
    -f deploy/compose.forward.yml \
    -f deploy/compose.solana-forward.yml \
    -f deploy/compose.lifecycle.yml \
    -f deploy/compose.dashboard-tunnel.yml \
    -f deploy/compose.alerts.yml \
    -f deploy/compose.controls.yml \
    --profile forward \
    --profile solana \
    --profile lifecycle \
    --profile dashboard \
    --profile alerts \
    --profile controls \
    config >/dev/null

  printf '%s\n' '==> dashboard-local Docker Compose render'
  POSTGRES_PASSWORD=verify-postgres-password-long-enough \
  FORWARD_INGEST_SECRET=verify-forward-ingest-secret-long-enough \
  DASHBOARD_DB_PASSWORD=verify_dashboard_password_long_enough \
  SIGNER_ENABLED=false \
  docker compose \
    -f docker-compose.yml \
    -f deploy/compose.forward.yml \
    -f deploy/compose.dashboard-local.yml \
    --profile dashboard-local \
    config >/dev/null
else
  printf '%s\n' 'SKIP: Docker Compose unavailable; Python/migration checks passed.'
fi

printf '%s\n' 'VERIFIED: local Edge Lab repository checks passed.'
