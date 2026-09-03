#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.forward"

fail() { echo "CORE PRECHECK FAILED: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

command -v docker >/dev/null 2>&1 || fail "docker is not installed"
command -v python3 >/dev/null 2>&1 || fail "python3 is not installed"
docker info >/dev/null 2>&1 || fail "Docker daemon is not reachable"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is not available"

[ -f "$ENV_FILE" ] || fail "missing $ENV_FILE; run sh deploy/init-forward-env.sh first"
if mode=$(stat -c '%a' "$ENV_FILE" 2>/dev/null); then
  case "$mode" in 600|400) ;; *) fail "$ENV_FILE permissions are $mode; expected 600 or 400" ;; esac
fi
if grep -Eiq '^[A-Za-z0-9_]*(PRIVATE_KEY|SEED_PHRASE|MNEMONIC)=' "$ENV_FILE"; then
  fail "$ENV_FILE must not contain wallet/private-key/seed material"
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${FORWARD_INGEST_SECRET:?FORWARD_INGEST_SECRET is required}"
[ "${SIGNER_ENABLED:-false}" = "false" ] || fail "SIGNER_ENABLED must be false"
[ "${#POSTGRES_PASSWORD}" -ge 24 ] || fail "POSTGRES_PASSWORD must be at least 24 characters"
[ "${#FORWARD_INGEST_SECRET}" -ge 32 ] || fail "FORWARD_INGEST_SECRET must be at least 32 characters"
[ "$POSTGRES_PASSWORD" != "$FORWARD_INGEST_SECRET" ] || fail "application and ingest secrets must differ"

ARGS="--env-file $ENV_FILE -f docker-compose.yml -f deploy/compose.forward.yml --profile forward"
# shellcheck disable=SC2086
docker compose $ARGS config -q
# shellcheck disable=SC2086
services=$(docker compose $ARGS config --services)
for service in postgres redis migrate api hyperliquid-collector hyperliquid-forward-bootstrap hyperliquid-forward-runner polymarket-collector polymarket-forward-bootstrap polymarket-forward-runner forward-evaluator db-backup; do
  printf '%s\n' "$services" | grep -Fxq "$service" || fail "missing core service: $service"
done
for service in solana-launch-collector solana-forensic-sampler solana-forward-bootstrap solana-forward-runner; do
  if printf '%s\n' "$services" | grep -Fxq "$service"; then
    fail "Solana service unexpectedly selected before provider keys are configured: $service"
  fi
done

# Keep rendered values inside the pipe because they include internal secrets.
# shellcheck disable=SC2086
docker compose $ARGS config --format json | python3 -c '
import json, sys
services=json.load(sys.stdin).get("services", {})
def fail(msg): raise SystemExit("CORE PRECHECK FAILED: "+msg)
def ports(name): return services.get(name, {}).get("ports") or []
for name in ("postgres","redis"):
    if ports(name): fail(name+" must not publish a host port")
api=ports("api")
if len(api)!=1: fail("API must have exactly one loopback binding")
p=api[0]
if str(p.get("host_ip") or "")!="127.0.0.1" or str(p.get("published"))!="8000" or str(p.get("target"))!="8000":
    fail("API must bind only 127.0.0.1:8000")
for name in ("api","hyperliquid-forward-runner","polymarket-forward-runner","forward-evaluator"):
    env=services.get(name,{}).get("environment") or {}
    if str(env.get("SIGNER_ENABLED","")).lower()!="false": fail(name+" does not force signer off")
'

pass "Hyperliquid/Polymarket core can start without Helius/Jupiter"
