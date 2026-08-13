#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.forward"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Copy deploy/.env.forward.example and set secrets." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${FORWARD_INGEST_SECRET:?FORWARD_INGEST_SECRET is required}"
: "${DASHBOARD_DB_PASSWORD:?DASHBOARD_DB_PASSWORD is required}"
: "${HELIUS_API_KEY:?HELIUS_API_KEY is required for Solana forward research}"
: "${JUPITER_API_KEY:?JUPITER_API_KEY is required for quote-only Solana forward research}"

if [ "$POSTGRES_PASSWORD" = "replace-with-a-long-random-password" ] || \
   [ "$FORWARD_INGEST_SECRET" = "replace-with-a-separate-long-random-secret" ] || \
   [ "$DASHBOARD_DB_PASSWORD" = "replace-with-a-third-long-random-password" ]; then
  echo "Refusing to start with example secrets." >&2
  exit 1
fi

if [ "${SIGNER_ENABLED:-false}" != "false" ]; then
  echo "Refusing forward research deployment with SIGNER_ENABLED != false." >&2
  exit 1
fi

export SIGNER_ENABLED=false

COMPOSE_FILES="-f docker-compose.yml -f deploy/compose.forward.yml -f deploy/compose.solana-forward.yml -f deploy/compose.dashboard.yml"

# shellcheck disable=SC2086
docker compose --env-file "$ENV_FILE" $COMPOSE_FILES --profile forward --profile solana up -d --build \
  postgres redis migrate api dashboard-db-role dashboard \
  hyperliquid-collector hyperliquid-forward-bootstrap hyperliquid-forward-runner \
  polymarket-collector polymarket-forward-bootstrap polymarket-forward-runner \
  solana-launch-collector solana-forensic-sampler solana-forward-bootstrap solana-forward-runner \
  forward-evaluator db-backup

# shellcheck disable=SC2086
docker compose --env-file "$ENV_FILE" $COMPOSE_FILES --profile forward --profile solana ps

printf '\nDashboard gateway: http://127.0.0.1:8080/dashboard\n'
printf 'Private research API: http://127.0.0.1:8000 (never use as the Cloudflare origin)\n'
