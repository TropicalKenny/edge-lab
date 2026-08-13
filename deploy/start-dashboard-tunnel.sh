#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.forward"

sh deploy/preflight-forward.sh

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

export SIGNER_ENABLED=false

docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.solana-forward.yml \
  -f deploy/compose.dashboard-tunnel.yml \
  --profile dashboard \
  up -d --build dashboard-db-role dashboard cloudflared

docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.solana-forward.yml \
  -f deploy/compose.dashboard-tunnel.yml \
  --profile dashboard \
  ps dashboard cloudflared

cat <<'EOF'
Dashboard tunnel started.
Cloudflare's remotely managed Public Hostname must target: http://dashboard:8080
Never point the public hostname at api:8000. Keep it behind an owner-only Cloudflare Access application.
EOF
