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
: "${DASHBOARD_DB_PASSWORD:?DASHBOARD_DB_PASSWORD is required}"
: "${CLOUDFLARE_TUNNEL_TOKEN:?CLOUDFLARE_TUNNEL_TOKEN is required}"

if [ "$DASHBOARD_DB_PASSWORD" = "$POSTGRES_PASSWORD" ] || [ ${#DASHBOARD_DB_PASSWORD} -lt 24 ]; then
  echo "Dashboard DB password must be separate from PostgreSQL admin and at least 24 characters." >&2
  exit 1
fi
case "$DASHBOARD_DB_PASSWORD" in
  *[!A-Za-z0-9_-]*)
    echo "Dashboard DB password must use only URL-safe A-Z, a-z, 0-9, _ and - characters." >&2
    exit 1
    ;;
esac
case "$CLOUDFLARE_TUNNEL_TOKEN" in
  replace-with-*|example-*|changeme|CHANGE_ME)
    echo "Refusing to start with an example Cloudflare Tunnel token." >&2
    exit 1
    ;;
esac
if [ "${SIGNER_ENABLED:-false}" != "false" ]; then
  echo "Refusing dashboard deployment with SIGNER_ENABLED != false." >&2
  exit 1
fi

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
