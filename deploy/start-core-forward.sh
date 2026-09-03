#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.forward"

sh deploy/preflight-core-forward.sh

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
export SIGNER_ENABLED=false

ARGS="--env-file $ENV_FILE -f docker-compose.yml -f deploy/compose.forward.yml --profile forward"

# Start the two public-data forward programmes now. Solana remains deliberately absent
# until Helius/Jupiter are configured and the full Solana preflight is used.
# shellcheck disable=SC2086
docker compose $ARGS up -d --build \
  postgres redis migrate api \
  hyperliquid-collector hyperliquid-forward-bootstrap hyperliquid-forward-runner \
  polymarket-collector polymarket-forward-bootstrap polymarket-forward-runner \
  forward-evaluator db-backup

# Register the frozen Solana study so the owner surfaces can display/control it even
# before the Solana collectors are authorized to start. This performs no API request.
# shellcheck disable=SC2086
docker compose $ARGS run --rm --no-deps \
  -e DATABASE_URL="postgresql+psycopg://edge:${POSTGRES_PASSWORD}@postgres:5432/edge" \
  -e SIGNER_ENABLED=false \
  api python -m app.workers.solana_forward_bootstrap

# shellcheck disable=SC2086
docker compose $ARGS ps
