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
: "${DASHBOARD_DB_PASSWORD:?DASHBOARD_DB_PASSWORD is required for hosted mode}"
: "${CLOUDFLARE_TUNNEL_TOKEN:?CLOUDFLARE_TUNNEL_TOKEN is required for hosted mode}"

if [ "$POSTGRES_PASSWORD" = "replace-with-a-long-random-password" ] || \
   [ "$FORWARD_INGEST_SECRET" = "replace-with-a-separate-long-random-secret" ]; then
  echo "Refusing to start with example secrets." >&2
  exit 1
fi

if [ "$DASHBOARD_DB_PASSWORD" = "$POSTGRES_PASSWORD" ] || [ ${#DASHBOARD_DB_PASSWORD} -lt 24 ]; then
  echo "Dashboard DB password must be separate from PostgreSQL admin and at least 24 characters." >&2
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

# Start the private research stack first. PostgreSQL/Redis are never published and
# the internal API remains bound to 127.0.0.1 on the VPS.
sh deploy/start-forward.sh

# The Cloudflare tunnel must be remotely configured to route the protected hostname
# to http://dashboard:8080 — never to api:8000.
docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.solana-forward.yml \
  -f deploy/compose.hosted.yml \
  --profile forward \
  --profile solana \
  up -d --build dashboard-db-role dashboard cloudflared

docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.solana-forward.yml \
  -f deploy/compose.hosted.yml \
  --profile forward \
  --profile solana \
  ps api dashboard cloudflared
