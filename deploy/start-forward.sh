#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.forward"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Copy deploy/.env.forward.example and set secrets." >&2
  exit 1
fi

# A normal research launch cannot bypass signer/secret/network validation.
# Dashboard/tunnel credentials are intentionally not required for this private stack.
sh deploy/preflight-forward.sh --research-only

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${FORWARD_INGEST_SECRET:?FORWARD_INGEST_SECRET is required}"
: "${JUPITER_API_KEY:?JUPITER_API_KEY is required for quote-only Solana forward research}"

if [ -n "${SOLANA_RPC_HTTP_URL:-}" ] || [ -n "${SOLANA_RPC_WS_URL:-}" ]; then
  [ -n "${SOLANA_RPC_HTTP_URL:-}" ] && [ -n "${SOLANA_RPC_WS_URL:-}" ] || {
    echo "SOLANA_RPC_HTTP_URL and SOLANA_RPC_WS_URL must be configured together." >&2
    exit 1
  }
elif [ -z "${HELIUS_API_KEY:-}" ]; then
  echo "Solana research requires standard SOLANA_RPC_HTTP_URL + SOLANA_RPC_WS_URL or legacy HELIUS_API_KEY." >&2
  exit 1
fi

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
  -f deploy/compose.solana-forward.yml \
  -f deploy/compose.m6j.yml \
  --profile forward \
  --profile solana \
  --profile research-acceleration \
  up -d --build \
    postgres redis migrate api \
    hyperliquid-collector hyperliquid-forward-bootstrap hyperliquid-forward-runner \
    polymarket-collector polymarket-forward-bootstrap polymarket-forward-runner \
    solana-launch-collector solana-forensic-sampler solana-forward-bootstrap solana-forward-runner \
    m6l-solana-bootstrap m6l-solana-runner \
    m6j-hyperliquid-research m6j-polymarket-research m6j-solana-research \
    forward-evaluator db-backup

docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.solana-forward.yml \
  -f deploy/compose.m6j.yml \
  --profile forward \
  --profile solana \
  --profile research-acceleration \
  ps
