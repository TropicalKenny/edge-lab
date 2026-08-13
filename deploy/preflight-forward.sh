#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.forward"
WITH_TUNNEL=1

if [ "${1:-}" = "--research-only" ]; then
  WITH_TUNNEL=0
elif [ -n "${1:-}" ]; then
  echo "Usage: sh deploy/preflight-forward.sh [--research-only]" >&2
  exit 2
fi

fail() {
  echo "PRECHECK FAILED: $*" >&2
  exit 1
}

pass() {
  echo "PASS: $*"
}

command -v docker >/dev/null 2>&1 || fail "docker is not installed"
command -v python3 >/dev/null 2>&1 || fail "python3 is not installed"
docker info >/dev/null 2>&1 || fail "Docker daemon is not reachable"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is not available"
pass "Docker and Compose are available"

[ -f "$ENV_FILE" ] || fail "missing $ENV_FILE; copy deploy/.env.forward.example first"

if mode=$(stat -c '%a' "$ENV_FILE" 2>/dev/null); then
  case "$mode" in
    600|400) ;;
    *) fail "$ENV_FILE permissions are $mode; run: chmod 600 $ENV_FILE" ;;
  esac
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
: "${DASHBOARD_DB_PASSWORD:?DASHBOARD_DB_PASSWORD is required for the read-only dashboard}"
: "${HELIUS_API_KEY:?HELIUS_API_KEY is required for Solana research}"
: "${JUPITER_API_KEY:?JUPITER_API_KEY is required for quote-only Solana research}"

[ "${SIGNER_ENABLED:-false}" = "false" ] || fail "SIGNER_ENABLED must be false"
export SIGNER_ENABLED=false

case "$POSTGRES_PASSWORD" in
  replace-with-*|example-*|changeme|CHANGE_ME) fail "POSTGRES_PASSWORD is still an example value" ;;
esac
case "$FORWARD_INGEST_SECRET" in
  replace-with-*|example-*|changeme|CHANGE_ME) fail "FORWARD_INGEST_SECRET is still an example value" ;;
esac
case "$DASHBOARD_DB_PASSWORD" in
  replace-with-*|example-*|changeme|CHANGE_ME) fail "DASHBOARD_DB_PASSWORD is still an example value" ;;
esac

[ "${#POSTGRES_PASSWORD}" -ge 24 ] || fail "POSTGRES_PASSWORD must be at least 24 characters"
[ "${#FORWARD_INGEST_SECRET}" -ge 32 ] || fail "FORWARD_INGEST_SECRET must be at least 32 characters"
[ "${#DASHBOARD_DB_PASSWORD}" -ge 24 ] || fail "DASHBOARD_DB_PASSWORD must be at least 24 characters"
[ "$POSTGRES_PASSWORD" != "$FORWARD_INGEST_SECRET" ] || fail "POSTGRES_PASSWORD must differ from FORWARD_INGEST_SECRET"
[ "$DASHBOARD_DB_PASSWORD" != "$POSTGRES_PASSWORD" ] || fail "DASHBOARD_DB_PASSWORD must differ from POSTGRES_PASSWORD"
[ "$DASHBOARD_DB_PASSWORD" != "$FORWARD_INGEST_SECRET" ] || fail "DASHBOARD_DB_PASSWORD must differ from FORWARD_INGEST_SECRET"

if [ "$WITH_TUNNEL" -eq 1 ]; then
  : "${CLOUDFLARE_TUNNEL_TOKEN:?CLOUDFLARE_TUNNEL_TOKEN is required for dashboard preflight}"
  case "$CLOUDFLARE_TUNNEL_TOKEN" in
    replace-with-*|example-*|changeme|CHANGE_ME) fail "CLOUDFLARE_TUNNEL_TOKEN is still an example value" ;;
  esac
fi
pass "required research/deployment secrets are present without wallet material"

[ -f .gitignore ] || fail ".gitignore is missing"
grep -Fxq 'deploy/.env.forward' .gitignore || fail "deploy/.env.forward is not explicitly gitignored"
grep -Fxq 'deploy/backups/' .gitignore || fail "deploy/backups/ is not explicitly gitignored"
mkdir -p deploy/backups
chmod 700 deploy/backups
pass "real environment and backup directory are protected from Git tracking"

BASE_ARGS="--env-file $ENV_FILE -f docker-compose.yml -f deploy/compose.forward.yml -f deploy/compose.solana-forward.yml -f deploy/compose.dashboard.yml"
if [ "$WITH_TUNNEL" -eq 1 ]; then
  EXTRA_ARGS="-f deploy/compose.dashboard-tunnel.yml --profile dashboard"
else
  EXTRA_ARGS=""
fi

# shellcheck disable=SC2086
docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana config -q
# shellcheck disable=SC2086
services=$(docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana config --services)
pass "Docker Compose configuration renders successfully"

for service in \
  postgres redis migrate api dashboard-db-role dashboard \
  hyperliquid-collector hyperliquid-forward-bootstrap hyperliquid-forward-runner \
  polymarket-collector polymarket-forward-bootstrap polymarket-forward-runner \
  solana-launch-collector solana-forensic-sampler solana-forward-bootstrap solana-forward-runner \
  forward-evaluator db-backup
do
  printf '%s\n' "$services" | grep -Fxq "$service" || fail "rendered Compose stack is missing service: $service"
done
if [ "$WITH_TUNNEL" -eq 1 ]; then
  printf '%s\n' "$services" | grep -Fxq cloudflared || fail "rendered Compose stack is missing cloudflared"
fi
pass "all expected paper/shadow and dashboard services are present"

export EDGE_PREFLIGHT_WITH_TUNNEL="$WITH_TUNNEL"
# The rendered configuration contains secrets; keep it only in the pipe and never write it to disk/stdout.
# shellcheck disable=SC2086
docker compose $BASE_ARGS $EXTRA_ARGS --profile forward --profile solana config --format json |
  python3 -c '
import json, os, sys
cfg=json.load(sys.stdin)
services=cfg.get("services", {})
with_tunnel=os.environ.get("EDGE_PREFLIGHT_WITH_TUNNEL") == "1"

def fail(msg):
    raise SystemExit("PRECHECK FAILED: "+msg)

def ports(name):
    return services.get(name, {}).get("ports") or []

def networks(name):
    value=services.get(name, {}).get("networks") or {}
    if isinstance(value, dict):
        return set(value)
    return set(value)

def one_loopback(name, published, target):
    values=ports(name)
    if len(values)!=1:
        fail(name+" must have exactly one loopback host binding")
    p=values[0]
    if str(p.get("host_ip") or "")!="127.0.0.1":
        fail(name+" host binding is not 127.0.0.1")
    if str(p.get("published"))!=str(published) or str(p.get("target"))!=str(target):
        fail(name+" loopback port is incorrect")

if ports("postgres"): fail("PostgreSQL has a published host port")
if ports("redis"): fail("Redis has a published host port")
one_loopback("api", 8000, 8000)
one_loopback("dashboard", 8080, 8080)

for name in ("api","dashboard","hyperliquid-forward-runner","polymarket-forward-runner","solana-forward-runner","forward-evaluator"):
    env=services.get(name,{}).get("environment") or {}
    if str(env.get("SIGNER_ENABLED","")).lower()!="false": fail(name+" does not force SIGNER_ENABLED=false")

dashboard=services.get("dashboard", {})
dashboard_env=dashboard.get("environment") or {}
if set(dashboard_env) - {"DATABASE_URL","SIGNER_ENABLED"}:
    fail("dashboard receives unexpected environment variables")
db_url=str(dashboard_env.get("DATABASE_URL") or "")
if not db_url.startswith("postgresql+psycopg://edge_dashboard:") or not db_url.endswith("@postgres:5432/edge"):
    fail("dashboard does not use the dedicated edge_dashboard database login")
if "dashboard_gateway" not in networks("dashboard"):
    fail("dashboard is missing the isolated gateway network")
if "default" not in networks("dashboard"):
    fail("dashboard is missing the private database network")

role_command=str((services.get("dashboard-db-role", {}) or {}).get("command") or "")
for table in (
    "strategies","strategy_versions","strategy_evaluation_runs","forward_studies",
    "forward_nav_observations","forward_study_incidents","forward_trade_records","forward_execution_records",
):
    if table not in role_command: fail("dashboard role grant is missing table: "+table)
if "GRANT SELECT ON ALL TABLES" in role_command:
    fail("dashboard role grants SELECT on all tables")
if "GRANT INSERT" in role_command or "GRANT UPDATE" in role_command or "GRANT DELETE" in role_command:
    fail("dashboard role contains a write grant")

if with_tunnel:
    if ports("cloudflared"): fail("cloudflared has a published host port")
    cf=services.get("cloudflared", {})
    cf_env=cf.get("environment") or {}
    if set(cf_env) != {"TUNNEL_TOKEN"}: fail("cloudflared receives unexpected environment variables")
    if not cf_env.get("TUNNEL_TOKEN"): fail("cloudflared tunnel token is not injected")
    depends=cf.get("depends_on") or {}
    if "dashboard" not in depends: fail("cloudflared does not depend on the isolated dashboard service")
    if "api" in depends: fail("cloudflared must not depend on the research API")
    cf_networks=networks("cloudflared")
    if "dashboard_gateway" not in cf_networks: fail("cloudflared is missing dashboard_gateway")
    if cf_networks & networks("api"): fail("cloudflared shares a Docker network with the research API")
    if not (cf_networks & networks("dashboard")): fail("cloudflared cannot reach the dashboard gateway")
'
pass "rendered network, dashboard database and signer boundaries are fail-closed"

if [ "$WITH_TUNNEL" -eq 1 ]; then
  echo "READY: paper/shadow research + isolated authenticated dashboard deployment preflight passed"
else
  echo "READY: paper/shadow research + local read-only dashboard preflight passed (tunnel skipped)"
fi
