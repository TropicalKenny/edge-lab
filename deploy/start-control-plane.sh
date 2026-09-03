#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.forward"

sh deploy/preflight-controls.sh

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
export SIGNER_ENABLED=false

ARGS="--env-file $ENV_FILE -f docker-compose.yml -f deploy/compose.forward.yml -f deploy/compose.controls.yml --profile controls"

# The control plane depends only on PostgreSQL + migrations. It receives no venue/API keys.
# shellcheck disable=SC2086
docker compose $ARGS up -d --build \
  postgres migrate control-db-role owner-control telegram-controls

# Fail closed unless the private loopback service is healthy.
python3 - <<'PY'
import json
import time
import urllib.request

url = "http://127.0.0.1:8090/healthz"
last = None
for _ in range(20):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            payload = json.load(response)
        if (
            payload.get("status") == "ok"
            and payload.get("can_trade_live") is False
            and payload.get("can_sign") is False
            and payload.get("can_move_funds") is False
            and payload.get("shell_access") is False
        ):
            break
        last = f"unexpected health payload: {payload}"
    except Exception as exc:
        last = f"{type(exc).__name__}: {exc}"
    time.sleep(2)
else:
    raise SystemExit(f"owner-control health check failed: {last}")
PY

# shellcheck disable=SC2086
docker compose $ARGS ps owner-control telegram-controls

cat <<'EOF'
Edge Lab owner control plane is running on the VPS.
- owner-control: private loopback only (127.0.0.1:8090)
- telegram-controls: outbound long polling, no public port
- signer/live-capital capability: disabled
EOF
