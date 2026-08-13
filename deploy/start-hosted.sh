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
: "${HELIUS_API_KEY:?HELIUS_API_KEY is required for Solana forward research}"
: "${JUPITER_API_KEY:?JUPITER_API_KEY is required for quote-only Solana forward research}"
: "${CLOUDFLARE_TUNNEL_TOKEN:?CLOUDFLARE_TUNNEL_TOKEN is required for hosted mode}"

if [ "$POSTGRES_PASSWORD" = "replace-with-a-long-random-password" ] || \
   [ "$FORWARD_INGEST_SECRET" = "replace-with-a-separate-long-random-secret" ]; then
  echo "Refusing to start with example secrets." >&2
  exit 1
fi

if [ "${SIGNER_ENABLED:-false}" != "false" ]; then
  echo "Refusing hosted research deployment with SIGNER_ENABLED != false." >&2
  exit 1
fi

if [ "${CLOUDFLARE_TUNNEL_TOKEN}" = "replace-with-cloudflare-tunnel-token" ]; then
  echo "Refusing to start with an example tunnel token." >&2
  exit 1
fi

export SIGNER_ENABLED=false

# Start the private research stack first. This keeps PostgreSQL/Redis private and
# binds the API to localhost even if cloudflared is unavailable.
sh deploy/start-forward.sh

# The remotely-managed tunnel must already route the protected hostname to
# http://api:8000. Cloudflare Access should be created before starting this service.
docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.solana-forward.yml \
  -f deploy/compose.hosted.yml \
  --profile forward \
  --profile solana \
  up -d cloudflared

docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.solana-forward.yml \
  -f deploy/compose.hosted.yml \
  --profile forward \
  --profile solana \
  ps api cloudflared
