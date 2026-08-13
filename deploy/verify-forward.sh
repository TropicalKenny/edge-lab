#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.forward"
WITH_TUNNEL=0
STRICT=0

for arg in "$@"; do
  case "$arg" in
    --with-dashboard) WITH_TUNNEL=1 ;;
    --strict) STRICT=1 ;;
    *) echo "Usage: sh deploy/verify-forward.sh [--with-dashboard] [--strict]" >&2; exit 2 ;;
  esac
done

fail() {
  echo "VERIFY FAILED: $*" >&2
  exit 1
}

pass() {
  echo "PASS: $*"
}

command -v docker >/dev/null 2>&1 || fail "docker is not installed"
command -v curl >/dev/null 2>&1 || fail "curl is not installed"
command -v python3 >/dev/null 2>&1 || fail "python3 is not installed"
[ -f "$ENV_FILE" ] || fail "missing $ENV_FILE"

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${DASHBOARD_DB_PASSWORD:?DASHBOARD_DB_PASSWORD is required}"
[ "${SIGNER_ENABLED:-false}" = "false" ] || fail "SIGNER_ENABLED must remain false"
export SIGNER_ENABLED=false

BASE_ARGS="--env-file $ENV_FILE -f docker-compose.yml -f deploy/compose.forward.yml -f deploy/compose.solana-forward.yml -f deploy/compose.dashboard.yml"
if [ "$WITH_TUNNEL" -eq 1 ]; then
  : "${CLOUDFLARE_TUNNEL_TOKEN:?CLOUDFLARE_TUNNEL_TOKEN is required with --with-dashboard}"
  EXTRA_ARGS="-f deploy/compose.dashboard-tunnel.yml --profile dashboard"
else
  EXTRA_ARGS=""
fi

# shellcheck disable=SC2086
running=$(docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana ps --status running --services)

for service in \
  postgres redis api dashboard \
  hyperliquid-collector hyperliquid-forward-runner \
  polymarket-collector polymarket-forward-runner \
  solana-launch-collector solana-forensic-sampler solana-forward-runner \
  forward-evaluator db-backup
do
  printf '%s\n' "$running" | grep -Fxq "$service" || fail "service is not running: $service"
done
if [ "$WITH_TUNNEL" -eq 1 ]; then
  printf '%s\n' "$running" | grep -Fxq cloudflared || fail "cloudflared is not running"
fi
pass "expected long-running research and dashboard services are running"

curl -fsS --max-time 10 http://127.0.0.1:8080/healthz |
  python3 -c '
import json, sys
payload=json.load(sys.stdin)
expected={
    "status":"ok",
    "mode":"dashboard-read-only",
    "can_trade_live":False,
    "can_sign":False,
    "can_move_funds":False,
    "vault_accessible":False,
    "signer_enabled":False,
    "live_capital_usd":0,
}
for key,value in expected.items():
    if payload.get(key)!=value:
        raise SystemExit("VERIFY FAILED: unsafe dashboard health flag: "+key)
' || fail "isolated dashboard health endpoint is unsafe or unavailable"
curl -fsS --max-time 10 http://127.0.0.1:8080/dashboard >/dev/null || fail "isolated dashboard route is unavailable"
curl -fsS --max-time 10 http://127.0.0.1:8080/dashboard/assets/dashboard.css >/dev/null || fail "dashboard CSS asset is unavailable"
curl -fsS --max-time 10 http://127.0.0.1:8080/dashboard/assets/dashboard.js >/dev/null || fail "dashboard JS asset is unavailable"
pass "isolated dashboard page, health and local assets respond on loopback"

for path in /forward/ops/studies /risk/evaluate /venues/hyperliquid/status /openapi.json /docs; do
  internal_status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:8080$path" || true)
  [ "$internal_status" = "404" ] || fail "isolated dashboard unexpectedly exposes internal path: $path"
done
pass "dashboard gateway does not expose internal research or documentation routes"

curl -fsS --max-time 10 http://127.0.0.1:8080/dashboard/api/summary |
  python3 -c '
import json, sys
payload=json.load(sys.stdin)
if payload.get("mode")!="read-only-dashboard":
    raise SystemExit("VERIFY FAILED: dashboard mode is not read-only-dashboard")
if payload.get("capital_scope")!="independent-simulated-forward-study-bankrolls":
    raise SystemExit("VERIFY FAILED: dashboard capital scope is ambiguous")
safety=payload.get("safety") or {}
expected={
    "can_trade_live": False,
    "can_sign": False,
    "can_move_funds": False,
    "vault_accessible": False,
    "signer_enabled": False,
    "live_capital_usd": 0,
}
for key,value in expected.items():
    if safety.get(key)!=value:
        raise SystemExit("VERIFY FAILED: unsafe dashboard flag: "+key)
'
pass "dashboard runtime safety and simulated-capital flags remain explicit"

# Prove the dashboard database login can read only the allowlisted dashboard tables
# and has no table-write privileges. This performs privilege introspection only; it
# never attempts a write transaction.
# shellcheck disable=SC2086
docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana exec -T dashboard \
  python -c '
from sqlalchemy import create_engine, text
from app.config import get_settings
expected={
    "strategies","strategy_versions","strategy_evaluation_runs","forward_studies",
    "forward_nav_observations","forward_study_incidents","forward_trade_records","forward_execution_records",
}
engine=create_engine(get_settings().database_url)
with engine.connect() as conn:
    user=conn.scalar(text("SELECT current_user"))
    if user!="edge_dashboard":
        raise SystemExit("VERIFY FAILED: dashboard is not using edge_dashboard")
    rows=set(conn.execute(text("""
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND has_table_privilege(current_user, 'public.' || quote_ident(tablename), 'SELECT')
    """)).scalars())
    if rows!=expected:
        raise SystemExit("VERIFY FAILED: dashboard SELECT table set differs from allowlist")
    for table in expected:
        for privilege in ("INSERT","UPDATE","DELETE","TRUNCATE","REFERENCES","TRIGGER"):
            allowed=conn.scalar(text("SELECT has_table_privilege(current_user, :table, :privilege)"), {"table":"public."+table,"privilege":privilege})
            if allowed:
                raise SystemExit("VERIFY FAILED: dashboard has "+privilege+" on "+table)
' || fail "dashboard database privilege verification failed"
pass "dashboard database role is exact-table SELECT-only"

if [ "$WITH_TUNNEL" -eq 1 ]; then
  # Runtime network inspection: cloudflared and the research API must share no
  # Docker network. The dashboard is the only application service reachable by
  # cloudflared on dashboard_gateway.
  # shellcheck disable=SC2086
  api_id=$(docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana ps -q api)
  # shellcheck disable=SC2086
  dashboard_id=$(docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana ps -q dashboard)
  # shellcheck disable=SC2086
  cloudflared_id=$(docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana ps -q cloudflared)
  [ -n "$api_id" ] && [ -n "$dashboard_id" ] && [ -n "$cloudflared_id" ] || fail "cannot inspect dashboard tunnel containers"

  api_networks=$(docker inspect -f '{{range $k, $_ := .NetworkSettings.Networks}}{{$k}} {{end}}' "$api_id")
  dashboard_networks=$(docker inspect -f '{{range $k, $_ := .NetworkSettings.Networks}}{{$k}} {{end}}' "$dashboard_id")
  cloudflared_networks=$(docker inspect -f '{{range $k, $_ := .NetworkSettings.Networks}}{{$k}} {{end}}' "$cloudflared_id")
  shared_dashboard=0
  for network in $cloudflared_networks; do
    case " $api_networks " in *" $network "*) fail "cloudflared shares Docker network with research API: $network" ;; esac
    case " $dashboard_networks " in *" $network "*) shared_dashboard=1 ;; esac
  done
  [ "$shared_dashboard" -eq 1 ] || fail "cloudflared does not share a network with dashboard"
  pass "cloudflared is network-isolated from the research API"
fi

if [ "$STRICT" -eq 1 ]; then
  : "${HYPERLIQUID_FORWARD_STUDY_EXTERNAL_ID:=hyperliquid-btc-carry-m6c-v1}"
  : "${POLYMARKET_FORWARD_STUDY_EXTERNAL_ID:=polymarket-structural-m6f-v1}"
  : "${SOLANA_FORWARD_STUDY_EXTERNAL_ID:=solana-pump-baseline-m6g-v1}"

  # shellcheck disable=SC2086
  docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana exec -T hyperliquid-forward-runner \
    python -m app.forward_ops status --external-id "$HYPERLIQUID_FORWARD_STUDY_EXTERNAL_ID" --require-ready --quiet \
    || fail "Hyperliquid forward study is not ready"
  # shellcheck disable=SC2086
  docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana exec -T polymarket-forward-runner \
    python -m app.polymarket_forward_ops status --external-id "$POLYMARKET_FORWARD_STUDY_EXTERNAL_ID" --require-ready --quiet \
    || fail "Polymarket forward study is not ready"
  # shellcheck disable=SC2086
  docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana exec -T solana-forward-runner \
    python -m app.solana_forward_ops status --external-id "$SOLANA_FORWARD_STUDY_EXTERNAL_ID" --require-ready --quiet \
    || fail "Solana forward study is not ready"
  pass "all three frozen forward studies report ready"
fi

if [ "$WITH_TUNNEL" -eq 1 ]; then
  echo "VERIFIED: research stack and network-isolated private dashboard tunnel are running safely"
else
  echo "VERIFIED: research stack and isolated local dashboard are running safely"
fi
