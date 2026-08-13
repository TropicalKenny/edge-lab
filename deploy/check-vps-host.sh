#!/usr/bin/env bash
set -Eeuo pipefail

fail() { echo "HOST CHECK FAILED: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

[[ -r /etc/os-release ]] || fail "missing /etc/os-release"
# shellcheck disable=SC1091
. /etc/os-release
[[ ${ID:-} == "ubuntu" ]] || fail "Ubuntu Server is required"
case ${VERSION_ID:-} in 24.04|26.04) ;; *) fail "unsupported Ubuntu release: ${VERSION_ID:-unknown}" ;; esac
pass "supported Ubuntu release: ${VERSION_ID}"

min_cpu=${EDGE_MIN_VCPU:-4}
min_mem=${EDGE_MIN_MEMORY_MB:-7000}
min_disk=${EDGE_MIN_FREE_DISK_GB:-40}

cpus=$(nproc)
(( cpus >= min_cpu )) || fail "${cpus} vCPU available; need at least ${min_cpu}"
pass "vCPU capacity: ${cpus}"

mem_kb=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
mem_mb=$((mem_kb / 1024))
(( mem_mb >= min_mem )) || fail "${mem_mb} MB RAM available; need at least ${min_mem} MB"
pass "memory capacity: ${mem_mb} MB"

free_kb=$(df -Pk / | awk 'NR==2 {print $4}')
free_gb=$((free_kb / 1024 / 1024))
(( free_gb >= min_disk )) || fail "${free_gb} GB free on /; need at least ${min_disk} GB"
pass "free root disk: ${free_gb} GB"

command -v git >/dev/null 2>&1 || fail "git is missing"
command -v python3 >/dev/null 2>&1 || fail "python3 is missing"
command -v docker >/dev/null 2>&1 || fail "docker is missing"
docker info >/dev/null 2>&1 || fail "Docker daemon is not reachable"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is unavailable"
pass "Git, Python, Docker Engine and Compose are available"

if command -v systemctl >/dev/null 2>&1; then
  systemctl is-enabled docker >/dev/null 2>&1 || fail "Docker is not enabled at boot"
  systemctl is-active docker >/dev/null 2>&1 || fail "Docker is not running"
  pass "Docker service is enabled and active"
fi

if command -v timedatectl >/dev/null 2>&1; then
  sync=$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)
  [[ "$sync" == "yes" ]] || fail "system clock is not NTP synchronized"
  pass "system clock is NTP synchronized"
fi

if command -v ufw >/dev/null 2>&1; then
  state=$(ufw status 2>/dev/null | head -n1 || true)
  echo "INFO: ${state:-UFW status unavailable}"
fi

cat <<'EOF'
HOST READY: base VPS capacity/runtime checks passed.
This does not replace Edge Lab's application preflight (`sh deploy/preflight-forward.sh`).
EOF
