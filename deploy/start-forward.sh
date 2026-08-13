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

if [ "$POSTGRES_PASSWORD" = "replace-with-a-long-random-password" ] || \
   [ "$FORWARD_INGEST_SECRET" = "replace-with-a-separate-long-random-secret" ]; then
  echo "Refusing to start with example secrets." >&2
  exit 1
fi

if [ "${SIGNER_ENABLED:-false}" != "false" ]; then
  echo "Refusing forward research deployment with SIGNER_ENABLED != false." >&2
  exit 1
fi

export SIGNER_ENABLED=false

docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  --profile forward \
  up -d --build \
  postgres redis migrate api \
  hyperliquid-collector hyperliquid-forward-bootstrap hyperliquid-forward-runner \
  forward-evaluator polymarket-collector db-backup

docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  --profile forward \
  ps
