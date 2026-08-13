#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.forward"
[ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
mkdir -p deploy/backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)

docker compose \
  --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  exec -T postgres \
  sh -ec 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U edge -d edge -Fc' \
  > "deploy/backups/edge-$stamp.dump"

echo "Created deploy/backups/edge-$stamp.dump"
