#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.forward"
WITH_DASHBOARD=0
STRICT=0

for arg in "$@"; do
  case "$arg" in
    --with-dashboard) WITH_DASHBOARD=1 ;;
    --strict) STRICT=1 ;;
    *) echo "Usage: sh deploy/verify-forward.sh [--with-dashboard] [--strict]" >&2; exit 2 ;;
  esac
done

fail() { echo "VERIFY FAILED: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

command -v docker >/dev/null 2>&1 || fail "docker is not installed"
command -v curl >/dev/null 2>&1 || fail "curl is not installed"
command -v python3 >/dev/null 2>&1 || fail "python3 is not installed"
[ -f "$ENV_FILE" ] || fail "missing $ENV_FILE"

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
[ "${SIGNER_ENABLED:-false}" = "false" ] || fail "SIGNER_ENABLED must remain false"
export SIGNER_ENABLED=false

BASE_ARGS="--env-file $ENV_FILE -f docker-compose.yml -f deploy/compose.forward.yml -f deploy/compose.solana-forward.yml"
if [ "$WITH_DASHBOARD" -eq 1 ]; then
  : "${DASHBOARD_DB_PASSWORD:?DASHBOARD_DB_PASSWORD is required with --with-dashboard}"
  : "${CLOUDFLARE_TUNNEL_TOKEN:?CLOUDFLARE_TUNNEL_TOKEN is required with --with-dashboard}"
  EXTRA_ARGS="-f deploy/compose.dashboard-tunnel.yml --profile dashboard"
else
  EXTRA_ARGS=""
fi

# shellcheck disable=SC2086
running=$(docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana ps --status running --services)
for service in postgres redis api hyperliquid-collector hyperliquid-forward-runner polymarket-collector polymarket-forward-runner solana-launch-collector solana-forensic-sampler solana-forward-runner forward-evaluator db-backup; do
  printf '%s\n' "$running" | grep -Fxq "$service" || fail "service is not running: $service"
done
if [ "$WITH_DASHBOARD" -eq 1 ]; then
  for service in dashboard cloudflared; do
    printf '%s\n' "$running" | grep -Fxq "$service" || fail "service is not running: $service"
  done
fi
pass "expected long-running research services are running"

curl -fsS --max-time 10 http://127.0.0.1:8000/dashboard >/dev/null || fail "local internal dashboard route is unavailable"
curl -fsS --max-time 10 http://127.0.0.1:8000/dashboard/api/summary |
  python3 -c '
import json, sys
payload=json.load(sys.stdin)
if payload.get("mode")!="read-only-dashboard": raise SystemExit("VERIFY FAILED: dashboard mode is not read-only-dashboard")
safety=payload.get("safety") or {}
for key in ("can_trade_live","can_sign","can_move_funds","vault_accessible","signer_enabled"):
    if safety.get(key) is not False: raise SystemExit("VERIFY FAILED: unsafe dashboard flag: "+key)
'
pass "internal dashboard data reports fully disabled live capabilities"

if [ "$WITH_DASHBOARD" -eq 1 ]; then
  # Verify the exact service Cloudflare can reach, not merely the full internal API.
  # shellcheck disable=SC2086
  docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana exec -T dashboard python -c '
import json, urllib.error, urllib.request
base="http://127.0.0.1:8080"
health=json.load(urllib.request.urlopen(base+"/healthz", timeout=5))
if health.get("surface")!="dashboard-only" or health.get("can_sign") is not False:
    raise SystemExit("isolated dashboard health contract failed")
payload=json.load(urllib.request.urlopen(base+"/dashboard/api/summary", timeout=5))
if payload.get("mode")!="read-only-dashboard": raise SystemExit("isolated dashboard summary is not read-only")
try:
    urllib.request.urlopen(base+"/signer/status", timeout=5)
except urllib.error.HTTPError as exc:
    if exc.code!=404: raise
else:
    raise SystemExit("isolated dashboard unexpectedly exposes signer route")
' || fail "isolated dashboard service boundary failed"
  pass "Cloudflare-facing dashboard surface is read-only and excludes signer routes"
fi

if [ "$STRICT" -eq 1 ]; then
  : "${HYPERLIQUID_FORWARD_STUDY_EXTERNAL_ID:=hyperliquid-btc-carry-m6c-v1}"
  : "${POLYMARKET_FORWARD_STUDY_EXTERNAL_ID:=polymarket-structural-m6f-v1}"
  : "${SOLANA_FORWARD_STUDY_EXTERNAL_ID:=solana-pump-baseline-m6g-v1}"
  # shellcheck disable=SC2086
  docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana exec -T hyperliquid-forward-runner python -m app.forward_ops status --external-id "$HYPERLIQUID_FORWARD_STUDY_EXTERNAL_ID" --require-ready --quiet || fail "Hyperliquid forward study is not ready"
  # shellcheck disable=SC2086
  docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana exec -T polymarket-forward-runner python -m app.polymarket_forward_ops status --external-id "$POLYMARKET_FORWARD_STUDY_EXTERNAL_ID" --require-ready --quiet || fail "Polymarket forward study is not ready"
  # shellcheck disable=SC2086
  docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana exec -T solana-forward-runner python -m app.solana_forward_ops status --external-id "$SOLANA_FORWARD_STUDY_EXTERNAL_ID" --require-ready --quiet || fail "Solana forward study is not ready"
  pass "all three frozen forward studies report ready"
fi

if [ "$WITH_DASHBOARD" -eq 1 ]; then
  echo "VERIFIED: research stack and isolated private dashboard tunnel are running safely"
else
  echo "VERIFIED: research stack is running safely"
fi
