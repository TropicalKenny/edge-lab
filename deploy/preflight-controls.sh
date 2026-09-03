#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.forward"

fail() { echo "CONTROL PRECHECK FAILED: $*" >&2; exit 1; }
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
: "${CONTROL_DB_PASSWORD:?CONTROL_DB_PASSWORD is required}"
: "${OWNER_CONTROL_API_TOKEN:?OWNER_CONTROL_API_TOKEN is required}"
: "${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN is required}"
: "${TELEGRAM_CHAT_ID:?TELEGRAM_CHAT_ID is required}"
: "${TELEGRAM_OWNER_USER_ID:?TELEGRAM_OWNER_USER_ID is required}"
[ "${SIGNER_ENABLED:-false}" = "false" ] || fail "SIGNER_ENABLED must be false"

[ "${#POSTGRES_PASSWORD}" -ge 24 ] || fail "POSTGRES_PASSWORD must be at least 24 characters"
[ "${#CONTROL_DB_PASSWORD}" -ge 24 ] || fail "CONTROL_DB_PASSWORD must be at least 24 characters"
[ "${#OWNER_CONTROL_API_TOKEN}" -ge 32 ] || fail "OWNER_CONTROL_API_TOKEN must be at least 32 characters"
[ "$CONTROL_DB_PASSWORD" != "$POSTGRES_PASSWORD" ] || fail "control DB password must differ from application DB password"
[ "$OWNER_CONTROL_API_TOKEN" != "$POSTGRES_PASSWORD" ] || fail "owner API token must differ from DB password"
[ "$OWNER_CONTROL_API_TOKEN" != "$CONTROL_DB_PASSWORD" ] || fail "owner API token must differ from control DB password"

case "$CONTROL_DB_PASSWORD" in *[!A-Za-z0-9_-]*) fail "CONTROL_DB_PASSWORD must be URL-safe" ;; esac
case "$OWNER_CONTROL_API_TOKEN" in *[!A-Za-z0-9_-]*) fail "OWNER_CONTROL_API_TOKEN must be URL-safe" ;; esac

ARGS="--env-file $ENV_FILE -f docker-compose.yml -f deploy/compose.forward.yml -f deploy/compose.controls.yml --profile controls"
# shellcheck disable=SC2086
docker compose $ARGS config -q

# Rendered JSON includes interpolated credentials; never write it to disk.
# shellcheck disable=SC2086
docker compose $ARGS config --format json | python3 -c '
import json, sys
services=json.load(sys.stdin).get("services", {})
def fail(msg): raise SystemExit("CONTROL PRECHECK FAILED: "+msg)
def ports(name): return services.get(name, {}).get("ports") or []
for name in ("control-db-role","telegram-controls"):
    if ports(name): fail(name+" must not publish a host port")
owner_ports=ports("owner-control")
if len(owner_ports)!=1: fail("owner-control must have exactly one loopback binding")
p=owner_ports[0]
if str(p.get("host_ip") or "")!="127.0.0.1" or str(p.get("published"))!="8090" or str(p.get("target"))!="8090":
    fail("owner-control must bind only 127.0.0.1:8090")

telegram=services.get("telegram-controls", {})
tenv=telegram.get("environment") or {}
required={"DATABASE_URL","SIGNER_ENABLED","TELEGRAM_BOT_TOKEN","TELEGRAM_CHAT_ID","TELEGRAM_OWNER_USER_ID","TELEGRAM_TIMEOUT_SECONDS","TELEGRAM_CONTROL_POLL_TIMEOUT_SECONDS","TELEGRAM_CONTROL_RETRY_SECONDS"}
if set(tenv)!=required: fail("telegram-controls receives unexpected environment variables")
if not str(tenv.get("DATABASE_URL","")).startswith("postgresql+psycopg://edge_control:"):
    fail("telegram-controls does not use the dedicated edge_control role")
if str(tenv.get("SIGNER_ENABLED","")).lower()!="false": fail("telegram-controls does not force signer off")

owner=services.get("owner-control", {})
oenv=owner.get("environment") or {}
if set(oenv)!={"DATABASE_URL","SIGNER_ENABLED","OWNER_CONTROL_API_TOKEN"}:
    fail("owner-control receives unexpected environment variables")
if not str(oenv.get("DATABASE_URL","")).startswith("postgresql+psycopg://edge_control:"):
    fail("owner-control does not use the dedicated edge_control role")
if str(oenv.get("SIGNER_ENABLED","")).lower()!="false": fail("owner-control does not force signer off")

for name in ("owner-control","telegram-controls"):
    service=services.get(name,{})
    mounts=service.get("volumes") or []
    if any("docker.sock" in str(m) for m in mounts): fail(name+" must not receive the Docker socket")

role=str((services.get("control-db-role",{}) or {}).get("command") or "")
for required_text in (
    "REVOKE ALL ON ALL TABLES",
    "GRANT UPDATE (status) ON forward_studies",
    "GRANT UPDATE (resolved, resolved_at) ON forward_study_incidents",
    "GRANT INSERT ON owner_commands",
    "GRANT INSERT, UPDATE ON integration_cursors",
):
    if required_text not in role: fail("control role is missing least-privilege rule: "+required_text)
if "GRANT ALL" in role or "GRANT DELETE" in role or "GRANT UPDATE ON forward_studies" in role:
    fail("control role contains an overly broad write grant")
'

pass "Telegram and private owner-control services are isolated and signer-disabled"
