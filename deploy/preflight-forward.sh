#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.forward"
WITH_DASHBOARD=1

if [ "${1:-}" = "--research-only" ]; then
  WITH_DASHBOARD=0
elif [ -n "${1:-}" ]; then
  echo "Usage: sh deploy/preflight-forward.sh [--research-only]" >&2
  exit 2
fi

fail() { echo "PRECHECK FAILED: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

command -v docker >/dev/null 2>&1 || fail "docker is not installed"
command -v python3 >/dev/null 2>&1 || fail "python3 is not installed"
docker info >/dev/null 2>&1 || fail "Docker daemon is not reachable"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is not available"
pass "Docker and Compose are available"

[ -f "$ENV_FILE" ] || fail "missing $ENV_FILE; copy deploy/.env.forward.example first"
if mode=$(stat -c '%a' "$ENV_FILE" 2>/dev/null); then
  case "$mode" in 600|400) ;; *) fail "$ENV_FILE permissions are $mode; run: chmod 600 $ENV_FILE" ;; esac
fi
pass "deployment environment file exists with restricted permissions"

if grep -Eiq '^[A-Za-z0-9_]*(PRIVATE_KEY|SEED_PHRASE|MNEMONIC)=' "$ENV_FILE"; then
  fail "$ENV_FILE must not contain wallet/private-key/seed material"
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${FORWARD_INGEST_SECRET:?FORWARD_INGEST_SECRET is required}"
: "${JUPITER_API_KEY:?JUPITER_API_KEY is required for quote-only Solana research}"

if [ -n "${SOLANA_RPC_HTTP_URL:-}" ] || [ -n "${SOLANA_RPC_WS_URL:-}" ]; then
  [ -n "${SOLANA_RPC_HTTP_URL:-}" ] || fail "SOLANA_RPC_HTTP_URL is required when SOLANA_RPC_WS_URL is configured"
  [ -n "${SOLANA_RPC_WS_URL:-}" ] || fail "SOLANA_RPC_WS_URL is required when SOLANA_RPC_HTTP_URL is configured"
  case "$SOLANA_RPC_HTTP_URL" in https://*) ;; *) fail "SOLANA_RPC_HTTP_URL must use https://" ;; esac
  case "$SOLANA_RPC_WS_URL" in wss://*) ;; *) fail "SOLANA_RPC_WS_URL must use wss://" ;; esac
  pass "standard Solana RPC HTTP/WebSocket provider is configured"
elif [ -n "${HELIUS_API_KEY:-}" ]; then
  pass "legacy Helius Solana provider fallback is configured"
else
  fail "Solana research requires SOLANA_RPC_HTTP_URL + SOLANA_RPC_WS_URL or HELIUS_API_KEY"
fi

[ "${SIGNER_ENABLED:-false}" = "false" ] || fail "SIGNER_ENABLED must be false"
export SIGNER_ENABLED=false

case "$POSTGRES_PASSWORD" in replace-with-*|example-*|changeme|CHANGE_ME) fail "POSTGRES_PASSWORD is still an example value" ;; esac
case "$FORWARD_INGEST_SECRET" in replace-with-*|example-*|changeme|CHANGE_ME) fail "FORWARD_INGEST_SECRET is still an example value" ;; esac
[ "${#POSTGRES_PASSWORD}" -ge 24 ] || fail "POSTGRES_PASSWORD must be at least 24 characters"
[ "${#FORWARD_INGEST_SECRET}" -ge 32 ] || fail "FORWARD_INGEST_SECRET must be at least 32 characters"
[ "$POSTGRES_PASSWORD" != "$FORWARD_INGEST_SECRET" ] || fail "POSTGRES_PASSWORD must differ from FORWARD_INGEST_SECRET"

if [ "$WITH_DASHBOARD" -eq 1 ]; then
  : "${DASHBOARD_DB_PASSWORD:?DASHBOARD_DB_PASSWORD is required for dashboard preflight}"
  : "${CLOUDFLARE_TUNNEL_TOKEN:?CLOUDFLARE_TUNNEL_TOKEN is required for dashboard preflight}"
  [ "$DASHBOARD_DB_PASSWORD" != "$POSTGRES_PASSWORD" ] || fail "DASHBOARD_DB_PASSWORD must differ from POSTGRES_PASSWORD"
  [ "$DASHBOARD_DB_PASSWORD" != "$FORWARD_INGEST_SECRET" ] || fail "DASHBOARD_DB_PASSWORD must differ from FORWARD_INGEST_SECRET"
  [ "${#DASHBOARD_DB_PASSWORD}" -ge 24 ] || fail "DASHBOARD_DB_PASSWORD must be at least 24 characters"
  case "$DASHBOARD_DB_PASSWORD" in *[!A-Za-z0-9_-]*) fail "DASHBOARD_DB_PASSWORD must use only URL-safe A-Z, a-z, 0-9, _ and -" ;; esac
  case "$CLOUDFLARE_TUNNEL_TOKEN" in replace-with-*|example-*|changeme|CHANGE_ME) fail "CLOUDFLARE_TUNNEL_TOKEN is still an example value" ;; esac
fi
pass "required research/deployment secrets are present without wallet material"

[ -f .gitignore ] || fail ".gitignore is missing"
grep -Fxq 'deploy/.env.forward' .gitignore || fail "deploy/.env.forward is not explicitly gitignored"
grep -Fxq 'deploy/backups/' .gitignore || fail "deploy/backups/ is not explicitly gitignored"
mkdir -p deploy/backups
chmod 700 deploy/backups
pass "real environment and backup directory are protected from Git tracking"

BASE_ARGS="--env-file $ENV_FILE -f docker-compose.yml -f deploy/compose.forward.yml -f deploy/compose.solana-forward.yml"
if [ "$WITH_DASHBOARD" -eq 1 ]; then
  # shellcheck disable=SC2086
  docker compose $BASE_ARGS -f deploy/compose.dashboard-tunnel.yml --profile forward --profile solana --profile dashboard config -q
  # shellcheck disable=SC2086
  services=$(docker compose $BASE_ARGS -f deploy/compose.dashboard-tunnel.yml --profile forward --profile solana --profile dashboard config --services)
else
  # shellcheck disable=SC2086
  docker compose $BASE_ARGS --profile forward --profile solana config -q
  # shellcheck disable=SC2086
  services=$(docker compose $BASE_ARGS --profile forward --profile solana config --services)
fi
pass "Docker Compose configuration renders successfully"

for service in postgres redis migrate api hyperliquid-collector hyperliquid-forward-bootstrap hyperliquid-forward-runner polymarket-collector polymarket-forward-bootstrap polymarket-forward-runner solana-launch-collector solana-forensic-sampler solana-forward-bootstrap solana-forward-runner forward-evaluator db-backup; do
  printf '%s\n' "$services" | grep -Fxq "$service" || fail "rendered Compose stack is missing service: $service"
done
if [ "$WITH_DASHBOARD" -eq 1 ]; then
  for service in dashboard-db-role dashboard cloudflared; do
    printf '%s\n' "$services" | grep -Fxq "$service" || fail "rendered Compose stack is missing service: $service"
  done
fi
pass "all expected paper/shadow services are present"

if [ "$WITH_DASHBOARD" -eq 1 ]; then
  # Rendered JSON contains interpolated secrets; keep it in the pipe only.
  # shellcheck disable=SC2086
  docker compose $BASE_ARGS -f deploy/compose.dashboard-tunnel.yml --profile forward --profile solana --profile dashboard config --format json |
    python3 -c '
import json, sys
services=json.load(sys.stdin).get("services", {})
def fail(msg): raise SystemExit("PRECHECK FAILED: "+msg)
def ports(name): return services.get(name, {}).get("ports") or []
def networks(name):
    value=services.get(name, {}).get("networks") or {}
    return set(value.keys()) if isinstance(value, dict) else set(value)

for name in ("postgres","redis","dashboard","cloudflared"):
    if ports(name): fail(name+" has a published host port")
api_ports=ports("api")
if len(api_ports)!=1: fail("API must have exactly one loopback host binding")
p=api_ports[0]
if str(p.get("host_ip") or "")!="127.0.0.1": fail("API host binding is not 127.0.0.1")
if str(p.get("published"))!="8000" or str(p.get("target"))!="8000": fail("API loopback port must be 8000:8000")

for name in ("api","dashboard","hyperliquid-forward-runner","polymarket-forward-runner","solana-forward-runner","forward-evaluator"):
    env=services.get(name,{}).get("environment") or {}
    if str(env.get("SIGNER_ENABLED","")).lower()!="false": fail(name+" does not force SIGNER_ENABLED=false")

dash=services.get("dashboard", {})
dash_env=dash.get("environment") or {}
if set(dash_env)!={"DATABASE_URL","SIGNER_ENABLED"}: fail("dashboard receives unexpected environment variables")
if not str(dash_env.get("DATABASE_URL","")).startswith("postgresql+psycopg://edge_dashboard:"):
    fail("dashboard does not use edge_dashboard database role")
if not str(dash_env.get("DATABASE_URL","")).endswith("@postgres:5432/edge"):
    fail("dashboard database URL targets an unexpected database")

dash_networks=networks("dashboard")
if "dashboard_edge" not in dash_networks or "default" not in dash_networks:
    fail("dashboard must bridge only the private database and dashboard_edge networks")

role_command=str((services.get("dashboard-db-role", {}) or {}).get("command") or "")
for table in (
    "strategies","strategy_versions","strategy_evaluation_runs","forward_studies",
    "forward_nav_observations","forward_study_incidents","forward_trade_records","forward_execution_records",
):
    if table not in role_command: fail("dashboard role grant is missing table: "+table)
if "GRANT SELECT ON ALL TABLES" in role_command: fail("dashboard role grants SELECT on all tables")
if "GRANT INSERT" in role_command or "GRANT UPDATE" in role_command or "GRANT DELETE" in role_command:
    fail("dashboard role contains a write grant")
if "default_transaction_read_only = on" not in role_command:
    fail("dashboard role does not default transactions to read-only")

cf=services.get("cloudflared", {})
cf_env=cf.get("environment") or {}
if set(cf_env)!={"TUNNEL_TOKEN"}: fail("cloudflared receives unexpected environment variables")
if not cf_env.get("TUNNEL_TOKEN"): fail("cloudflared tunnel token is not injected")
cf_networks=networks("cloudflared")
if cf_networks!={"dashboard_edge"}: fail("cloudflared must be isolated to dashboard_edge")
if cf_networks & networks("api"): fail("cloudflared shares a Docker network with the research API")
if not (cf_networks & dash_networks): fail("cloudflared cannot reach the dashboard service")
'
else
  # shellcheck disable=SC2086
  docker compose $BASE_ARGS --profile forward --profile solana config --format json |
    python3 -c '
import json, sys
services=json.load(sys.stdin).get("services", {})
def fail(msg): raise SystemExit("PRECHECK FAILED: "+msg)
def ports(name): return services.get(name, {}).get("ports") or []
if ports("postgres"): fail("PostgreSQL has a published host port")
if ports("redis"): fail("Redis has a published host port")
api_ports=ports("api")
if len(api_ports)!=1 or str(api_ports[0].get("host_ip") or "")!="127.0.0.1": fail("API is not loopback-only")
for name in ("api","hyperliquid-forward-runner","polymarket-forward-runner","solana-forward-runner","forward-evaluator"):
    env=services.get(name,{}).get("environment") or {}
    if str(env.get("SIGNER_ENABLED","")).lower()!="false": fail(name+" does not force SIGNER_ENABLED=false")
'
fi
pass "rendered network, database and signer boundaries are fail-closed"

if [ "$WITH_DASHBOARD" -eq 1 ]; then
  echo "READY: paper/shadow research + isolated authenticated dashboard preflight passed"
else
  echo "READY: paper/shadow research deployment preflight passed (dashboard skipped)"
fi
