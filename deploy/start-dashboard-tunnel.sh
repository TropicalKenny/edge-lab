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

: "${CLOUDFLARE_TUNNEL_TOKEN:?CLOUDFLARE_TUNNEL_TOKEN is required}"

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
  up -d cloudflared

docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.solana-forward.yml \
  -f deploy/compose.dashboard-tunnel.yml \
  --profile dashboard \
  ps cloudflared

cat <<'EOF'
Dashboard tunnel started.
Cloudflare's remotely managed Public Hostname must target: http://api:8000
Keep the hostname behind an owner-only Cloudflare Access application.
EOF
