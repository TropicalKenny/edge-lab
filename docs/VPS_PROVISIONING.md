# Edge Lab — Fresh VPS Provisioning

This milestone prepares a fresh Ubuntu VPS for Edge Lab's paper/shadow research deployment. It does **not** deploy a wallet, private key, live signer or real capital.

## Supported host

- Ubuntu Server 24.04 LTS or 26.04 LTS
- amd64 or arm64
- recommended: 4 vCPU, 8 GB RAM, 100+ GB NVMe

The provisioner follows Docker's official Ubuntu apt-repository installation pattern and installs Docker Engine, CLI, containerd, Buildx and the Compose plugin. It deliberately refuses to remove pre-existing conflicting container packages automatically.

## Prepare the host

Copy or run the repository script on the new VPS as root:

```sh
bash deploy/provision-ubuntu.sh
```

It installs only host/runtime dependencies:

- CA certificates and curl;
- Git and Python 3;
- Docker Engine + Compose from Docker's official apt repository;
- UFW package;
- unattended security upgrades.

It does not clone the private repo, create application secrets, configure Cloudflare, or store wallet material.

### Optional host firewall

Cloudflare Tunnel does not require inbound HTTP/HTTPS ports. If the VPS SSH port is known and already working, UFW can be enabled explicitly:

```sh
EDGE_CONFIGURE_UFW=1 EDGE_SSH_PORT=22 bash deploy/provision-ubuntu.sh
```

Firewall configuration is off by default to avoid locking out an existing SSH session. Docker networking can bypass ordinary UFW expectations for published container ports, so Edge Lab separately enforces its own Compose boundary: PostgreSQL/Redis/dashboard have no host ports and the internal API is loopback-only.

A cloud-provider firewall/security group should likewise expose only the SSH port needed for administration. The dashboard arrives through outbound Cloudflare Tunnel.

## Verify host capacity

After provisioning:

```sh
bash deploy/check-vps-host.sh
```

Defaults:

- >=4 vCPU
- >=7000 MB RAM
- >=40 GB free root filesystem
- Docker enabled/running
- Docker Compose v2
- NTP-synchronized clock

Thresholds can be raised for a larger VPS:

```sh
EDGE_MIN_VCPU=8 EDGE_MIN_MEMORY_MB=15000 EDGE_MIN_FREE_DISK_GB=80 \
  bash deploy/check-vps-host.sh
```

## Deploy Edge Lab

Clone the private repository using the owner's chosen GitHub authentication method, then:

```sh
cd edge-lab
sh deploy/init-forward-env.sh
```

Add only the external research/hosting credentials:

- `HELIUS_API_KEY`
- `JUPITER_API_KEY`
- `CLOUDFLARE_TUNNEL_TOKEN`
- optional `GOPLUS_ACCESS_TOKEN`

Do not place a wallet private key, seed phrase, mnemonic or owner-vault credential on this research VPS.

Then run:

```sh
sh deploy/preflight-forward.sh
sh deploy/start-forward.sh
sh deploy/start-dashboard-tunnel.sh
sh deploy/verify-forward.sh --with-dashboard --strict
```

The final command becomes meaningful only after the forward workers have produced their required initial heartbeats/evidence.

## Updating the server

Application updates should follow a controlled Git pull/checkout, CI-green commit, preflight, container rebuild/restart and runtime verification. Do not run arbitrary unattended `git pull && docker compose up` jobs against an unverified branch.

OS security updates may install automatically, but planned reboots and Docker/application upgrades remain operator-controlled.
