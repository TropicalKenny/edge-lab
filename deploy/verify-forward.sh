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

# Private diagnostic path on the internal API. It is not the Cloudflare origin.
curl -fsS --max-time 10 http://127.0.0.1:8000/dashboard >/dev/null || fail "local internal dashboard route is unavailable"
curl -fsS --max-time 10 http://127.0.0.1:8000/dashboard/api/summary |
  python3 -c '
import json, sys
payload=json.load(sys.stdin)
if payload.get("mode")!="read-only-dashboard": raise SystemExit("VERIFY FAILED: internal dashboard mode is not read-only-dashboard")
if payload.get("capital_scope")!="independent-simulated-forward-study-bankrolls": raise SystemExit("VERIFY FAILED: internal dashboard capital scope is ambiguous")
safety=payload.get("safety") or {}
expected={"can_trade_live":False,"can_sign":False,"can_move_funds":False,"vault_accessible":False,"signer_enabled":False,"live_capital_usd":0}
for key,value in expected.items():
    if safety.get(key)!=value: raise SystemExit("VERIFY FAILED: unsafe internal dashboard flag: "+key)
'
pass "private diagnostic dashboard data reports simulated capital and disabled live capabilities"

if [ "$WITH_DASHBOARD" -eq 1 ]; then
  # Verify the exact application service Cloudflare can reach.
  # shellcheck disable=SC2086
  docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana exec -T dashboard python -c '
import json, urllib.error, urllib.request
base="http://127.0.0.1:8080"
health=json.load(urllib.request.urlopen(base+"/healthz", timeout=5))
expected_health={
    "status":"ok","surface":"dashboard-only","mode":"dashboard-read-only",
    "can_trade_live":False,"can_sign":False,"can_move_funds":False,
    "vault_accessible":False,"signer_enabled":False,"live_capital_usd":0,
}
for key,value in expected_health.items():
    if health.get(key)!=value: raise SystemExit("isolated dashboard health contract failed: "+key)
payload=json.load(urllib.request.urlopen(base+"/dashboard/api/summary", timeout=5))
if payload.get("mode")!="read-only-dashboard": raise SystemExit("isolated dashboard summary is not read-only")
if payload.get("capital_scope")!="independent-simulated-forward-study-bankrolls": raise SystemExit("isolated dashboard capital scope is ambiguous")
safety=payload.get("safety") or {}
expected_safety={"can_trade_live":False,"can_sign":False,"can_move_funds":False,"vault_accessible":False,"signer_enabled":False,"live_capital_usd":0}
for key,value in expected_safety.items():
    if safety.get(key)!=value: raise SystemExit("isolated dashboard unsafe flag: "+key)
for path in ("/signer/status","/risk/evaluate","/paper/simulate","/forward/ops/studies","/portfolio/allocate","/openapi.json","/docs"):
    try:
        urllib.request.urlopen(base+path, timeout=5)
    except urllib.error.HTTPError as exc:
        if exc.code!=404: raise
    else:
        raise SystemExit("isolated dashboard unexpectedly exposes internal path: "+path)
' || fail "isolated dashboard service boundary failed"
  pass "Cloudflare-facing dashboard surface exposes only read-only simulated research data"

  # Verify the real PostgreSQL grants of the dashboard identity. Introspection only;
  # this never attempts a write transaction.
  # shellcheck disable=SC2086
  docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana exec -T dashboard python -c '
from sqlalchemy import create_engine, text
from app.config import get_settings
expected={"strategies","strategy_versions","strategy_evaluation_runs","forward_studies","forward_nav_observations","forward_study_incidents","forward_trade_records","forward_execution_records"}
engine=create_engine(get_settings().database_url)
with engine.connect() as conn:
    user=conn.scalar(text("SELECT current_user"))
    if user!="edge_dashboard": raise SystemExit("VERIFY FAILED: dashboard is not using edge_dashboard")
    rows=set(conn.execute(text("""
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND has_table_privilege(current_user, 'public.' || quote_ident(tablename), 'SELECT')
    """)).scalars())
    if rows!=expected: raise SystemExit("VERIFY FAILED: dashboard SELECT table set differs from allowlist")
    for table in expected:
        for privilege in ("INSERT","UPDATE","DELETE","TRUNCATE","REFERENCES","TRIGGER"):
            allowed=conn.scalar(text("SELECT has_table_privilege(current_user, :table, :privilege)"), {"table":"public."+table,"privilege":privilege})
            if allowed: raise SystemExit("VERIFY FAILED: dashboard has "+privilege+" on "+table)
' || fail "dashboard database privilege verification failed"
  pass "dashboard database identity is exact-table SELECT-only"

  # Verify runtime Docker network separation. Cloudflared may share dashboard_edge
  # with the dashboard, but must share no network with the private research API.
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
  pass "cloudflared is network-isolated from the private research API"
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
  echo "VERIFIED: research stack and hardened isolated private dashboard tunnel are running safely"
else
  echo "VERIFIED: research stack is running safely"
fi
