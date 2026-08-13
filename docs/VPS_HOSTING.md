# Edge Lab — VPS + Cloudflare Hosted Dashboard

## Goal

Run the research workers continuously on one VPS while exposing only the read-only Edge Lab dashboard to the owner through Cloudflare Access.

The hosted surface is intentionally separate from `app.main`. `app.dashboard_server` mounts only the dashboard routes and `/healthz`; it does not mount risk, venue refresh/scan, research-ingestion, signer, treasury, or portfolio mutation APIs.

## Security shape

```text
Browser
  -> Cloudflare Access (deny by default)
  -> Cloudflare Tunnel
  -> dashboard:8080 (read-only ASGI service)
  -> edge_dashboard PostgreSQL role (SELECT only)

VPS-only:
  127.0.0.1:8000 -> internal Edge Lab API
  postgres        -> no host port
  redis           -> no host port
  workers         -> no host port
```

The hosted launcher creates/rotates a dedicated `edge_dashboard` PostgreSQL login, grants only CONNECT/USAGE/SELECT, and gives future tables SELECT through default privileges. The dashboard never receives the main `edge` database password.

The owner vault remains outside the VPS. `SIGNER_ENABLED=false` is forced by the launchers. No wallet or signing credential is required for hosted dashboard mode.

## Cloudflare preparation

Use a remotely-managed Cloudflare Tunnel.

1. Add the desired hostname to **Cloudflare Access** first (for example `edge.example.com`).
2. Create an **Allow** policy only for the owner's identity. Access is deny-by-default when no Allow policy matches.
3. Prefer a strong identity provider and MFA.
4. Create a remotely-managed Cloudflare Tunnel.
5. Add a published application route for the protected hostname with service URL `http://dashboard:8080`.
6. Do **not** route the tunnel to `api:8000`.
7. Enable **Protect with Access** for the tunnel route when available so `cloudflared` validates the Access token at the origin boundary.
8. Copy the connector token into uncommitted `deploy/.env.forward` as `CLOUDFLARE_TUNNEL_TOKEN`.

The Docker connector follows Cloudflare's remotely-managed tunnel pattern: `cloudflare/cloudflared:latest tunnel --no-autoupdate run --token ...`.

## VPS preparation

Initial target: approximately 4 vCPU, 8 GB RAM and 100+ GB NVMe. Install Docker Engine and the Docker Compose plugin, clone the private repository, then:

```sh
cp deploy/.env.forward.example deploy/.env.forward
chmod 600 deploy/.env.forward
```

Populate at least:

- `POSTGRES_PASSWORD`
- `FORWARD_INGEST_SECRET`
- `DASHBOARD_DB_PASSWORD` — a separate random value, at least 24 characters
- `HELIUS_API_KEY`
- `JUPITER_API_KEY`
- `CLOUDFLARE_TUNNEL_TOKEN`

GoPlus remains optional.

## Start

```sh
sh deploy/start-hosted.sh
```

The launcher starts the hardened forward-research stack, creates/updates the SELECT-only dashboard database role, starts the isolated dashboard, and finally starts Cloudflare Tunnel. The internal API remains `127.0.0.1:8000`; the dashboard has no published host port.

## Verify

```sh
docker compose \
  --env-file deploy/.env.forward \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.solana-forward.yml \
  -f deploy/compose.hosted.yml \
  --profile forward --profile solana ps
```

Expected:

- PostgreSQL/Redis have no published ports;
- internal API is only `127.0.0.1:8000`;
- dashboard has no host port;
- cloudflared is running;
- hosted dashboard uses `edge_dashboard`, not the admin DB role;
- all forward services keep `SIGNER_ENABLED=false`.

From the Internet, the hostname must require Cloudflare Access authentication before the dashboard loads.

## Operational boundary

Dashboard V1 can display research NAV, strategy evidence, paper/shadow trades and incidents. It cannot submit orders/swaps, enable signing, move/bridge funds, access the owner vault, promote strategies, or mutate frozen evidence.

Future controls should be separate authenticated, audited operations rather than exposing the internal API.
