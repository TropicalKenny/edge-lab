#!/usr/bin/env bash
set -Eeuo pipefail

# Edge Lab host preparation only. This script installs host dependencies; it does
# not clone the private repository, create application secrets, configure a wallet,
# or start Edge Lab research.

if [[ ${EUID} -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    exec sudo -E bash "$0" "$@"
  fi
  echo "Run this script as root (or install sudo)." >&2
  exit 1
fi

[[ -r /etc/os-release ]] || { echo "Missing /etc/os-release" >&2; exit 1; }
# shellcheck disable=SC1091
. /etc/os-release
[[ ${ID:-} == "ubuntu" ]] || { echo "This provisioner supports Ubuntu Server only." >&2; exit 1; }

case ${VERSION_ID:-} in
  24.04|26.04) ;;
  *)
    echo "Unsupported Ubuntu release: ${VERSION_ID:-unknown}. Use a currently supported LTS release and review the script." >&2
    exit 1
    ;;
esac

arch=$(dpkg --print-architecture)
case "$arch" in amd64|arm64) ;; *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; esac

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git python3 python3-venv ufw unattended-upgrades

if ! command -v docker >/dev/null 2>&1; then
  # Do not silently remove distribution/vendor container packages on a non-fresh host.
  conflicts=""
  for package in docker.io docker-compose docker-compose-v2 podman-docker containerd runc; do
    if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
      conflicts="$conflicts $package"
    fi
  done
  if [[ -n "$conflicts" ]]; then
    echo "Conflicting container packages are installed:$conflicts" >&2
    echo "Refusing to remove them automatically. Prepare a fresh VPS or review removal manually." >&2
    exit 1
  fi

  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc

  codename=${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}
  [[ -n "$codename" ]] || { echo "Unable to determine Ubuntu codename." >&2; exit 1; }

  cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${codename}
Components: stable
Architectures: ${arch}
Signed-By: /etc/apt/keyrings/docker.asc
EOF

  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

systemctl enable --now docker
docker info >/dev/null
docker compose version >/dev/null

# Security updates are enabled, but ordinary package upgrades remain operator-controlled.
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true

# Cloudflare Tunnel requires no inbound web port. Firewall changes are opt-in to
# avoid locking out an existing SSH setup. Docker-published ports require separate
# care; Edge Lab's deployment preflight independently rejects public app/DB ports.
if [[ ${EDGE_CONFIGURE_UFW:-0} == "1" ]]; then
  ssh_port=${EDGE_SSH_PORT:-22}
  [[ "$ssh_port" =~ ^[0-9]+$ ]] && (( ssh_port >= 1 && ssh_port <= 65535 )) || {
    echo "EDGE_SSH_PORT must be a valid TCP port." >&2
    exit 1
  }
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow "${ssh_port}/tcp"
  ufw --force enable
fi

cat <<EOF
Edge Lab host preparation complete.
Ubuntu: ${VERSION_ID} (${arch})
Docker: $(docker --version)
Compose: $(docker compose version --short)

Next:
  1. Clone TropicalKenny/edge-lab using your private GitHub access method.
  2. cd edge-lab
  3. sh deploy/init-forward-env.sh
  4. add Helius, Jupiter and Cloudflare Tunnel credentials only
  5. sh deploy/preflight-forward.sh

No wallet/private key belongs on this research VPS.
EOF
