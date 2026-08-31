#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.forward"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Run sh deploy/init-forward-env.sh first." >&2
  exit 1
fi

# Reuse the full private-research safety gate before enabling this optional worker.
sh deploy/preflight-forward.sh --research-only

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${JUPITER_API_KEY:?JUPITER_API_KEY is required for quote-only lifecycle research}"

if [ "${SIGNER_ENABLED:-false}" != "false" ]; then
  echo "Refusing lifecycle research deployment with SIGNER_ENABLED != false." >&2
  exit 1
fi
export SIGNER_ENABLED=false

docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.solana-forward.yml \
  -f deploy/compose.lifecycle.yml \
  --profile forward \
  --profile solana \
  --profile lifecycle \
  config -q

docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.solana-forward.yml \
  -f deploy/compose.lifecycle.yml \
  --profile forward \
  --profile solana \
  --profile lifecycle \
  up -d --build postgres migrate solana-lifecycle-research

docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.solana-forward.yml \
  -f deploy/compose.lifecycle.yml \
  --profile lifecycle \
  ps solana-lifecycle-research
