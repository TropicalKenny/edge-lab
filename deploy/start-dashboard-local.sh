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
: "${DASHBOARD_DB_PASSWORD:?DASHBOARD_DB_PASSWORD is required}"
[ "${SIGNER_ENABLED:-false}" = "false" ] || { echo "Refusing dashboard with SIGNER_ENABLED != false" >&2; exit 1; }
export SIGNER_ENABLED=false

ARGS="--env-file $ENV_FILE -f docker-compose.yml -f deploy/compose.forward.yml -f deploy/compose.dashboard-local.yml -f deploy/compose.trend.yml -f deploy/compose.carry-shadow.yml --profile dashboard-local --profile trend --profile carry-shadow"
# shellcheck disable=SC2086
docker compose $ARGS config -q
# shellcheck disable=SC2086
docker compose $ARGS up -d --build postgres migrate dashboard-db-role dashboard trend-research carry-shadow

python3 - <<'PY'
import json
import time
import urllib.request

url = "http://127.0.0.1:8080/healthz"
last = None
for _ in range(20):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            payload = json.load(response)
        if (
            payload.get("status") == "ok"
            and payload.get("mode") == "dashboard-read-only"
            and payload.get("can_trade_live") is False
            and payload.get("can_sign") is False
        ):
            break
        last = f"unexpected health payload: {payload}"
    except Exception as exc:
        last = f"{type(exc).__name__}: {exc}"
    time.sleep(2)
else:
    raise SystemExit(f"dashboard health check failed: {last}")
PY

# shellcheck disable=SC2086
docker compose $ARGS ps dashboard
printf '%s\n' "Edge Lab dashboard is healthy on VPS loopback: http://127.0.0.1:8080/dashboard"
