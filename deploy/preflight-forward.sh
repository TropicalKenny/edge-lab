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

[ "${#POSTGRES_PASSWORD}" -ge 24 ] || fail "POSTGRES_PASSWORD must be at least 24 characters"
[ "${#FORWARD_INGEST_SECRET}" -ge 32 ] || fail "FORWARD_INGEST_SECRET must be at least 32 characters"

if [ "$WITH_DASHBOARD" -eq 1 ]; then
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

for service in \
  postgres redis migrate api \
  hyperliquid-collector hyperliquid-forward-bootstrap hyperliquid-forward-runner \
  polymarket-collector polymarket-forward-bootstrap polymarket-forward-runner \
  solana-launch-collector solana-forensic-sampler solana-forward-bootstrap solana-forward-runner \
  forward-evaluator db-backup
do
  printf '%s\n' "$services" | grep -Fxq "$service" || fail "rendered Compose stack is missing service: $service"
done
if [ "$WITH_DASHBOARD" -eq 1 ]; then
  printf '%s\n' "$services" | grep -Fxq cloudflared || fail "rendered Compose stack is missing cloudflared"
fi
pass "all expected paper/shadow services are present"

export EDGE_PREFLIGHT_WITH_DASHBOARD="$WITH_DASHBOARD"
if [ "$WITH_DASHBOARD" -eq 1 ]; then
  # The rendered configuration contains secrets; keep it only in the pipe and never write it to disk/stdout.
  # shellcheck disable=SC2086
  docker compose $BASE_ARGS -f deploy/compose.dashboard-tunnel.yml --profile forward --profile solana --profile dashboard config --format json |
    python3 -c '
import json, os, sys
cfg=json.load(sys.stdin)
services=cfg.get("services", {})

def fail(msg):
    raise SystemExit("PRECHECK FAILED: "+msg)

def ports(name):
    return services.get(name, {}).get("ports") or []

if ports("postgres"): fail("PostgreSQL has a published host port")
if ports("redis"): fail("Redis has a published host port")
if ports("cloudflared"): fail("cloudflared has a published host port")
api_ports=ports("api")
if len(api_ports)!=1: fail("API must have exactly one loopback host binding")
p=api_ports[0]
host_ip=str(p.get("host_ip") or p.get("host_ip", ""))
if host_ip!="127.0.0.1": fail("API host binding is not 127.0.0.1")
if str(p.get("published"))!="8000" or str(p.get("target"))!="8000": fail("API loopback port must be 8000:8000")
for name in ("api","hyperliquid-forward-runner","polymarket-forward-runner","solana-forward-runner","forward-evaluator"):
    env=services.get(name,{}).get("environment") or {}
    if str(env.get("SIGNER_ENABLED","")).lower()!="false": fail(name+" does not force SIGNER_ENABLED=false")
cf_env=services.get("cloudflared",{}).get("environment") or {}
if not cf_env.get("TUNNEL_TOKEN"): fail("cloudflared tunnel token is not injected")
for forbidden in ("DATABASE_URL","POSTGRES_PASSWORD","HELIUS_API_KEY","JUPITER_API_KEY","GOPLUS_ACCESS_TOKEN"):
    if forbidden in cf_env: fail("cloudflared unexpectedly receives "+forbidden)
'
else
  # shellcheck disable=SC2086
  docker compose $BASE_ARGS --profile forward --profile solana config --format json |
    python3 -c '
import json, sys
cfg=json.load(sys.stdin); services=cfg.get("services", {})
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
pass "rendered network and signer boundaries are fail-closed"

if [ "$WITH_DASHBOARD" -eq 1 ]; then
  echo "READY: paper/shadow research + authenticated dashboard deployment preflight passed"
else
  echo "READY: paper/shadow research deployment preflight passed (dashboard skipped)"
fi
