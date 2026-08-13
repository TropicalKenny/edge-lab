# Edge Lab — VPS + Cloudflare Hosted Dashboard

## Goal

Run the research workers continuously on one VPS while exposing only the read-only Edge Lab dashboard to the owner through Cloudflare Access.

The hosted surface is intentionally separate from `app.main`. `app.dashboard_server` mounts only the dashboard routes and `/healthz`; it does not mount risk, venue refresh/scan, research-ingestion, signer, treasury, or portfolio mutation APIs.

## Security shape

```text
Browser
  -> Cloudflare Access (deny by default)
  -> Cloudflare Tunnel
  -> cloudflared [dashboard_edge only]
  -> dashboard:8080 [dashboard_edge + dashboard_data]
  -> edge_dashboard PostgreSQL role [SELECT only]
  -> postgres [dashboard_data + internal default network]

VPS-only/internal:
  127.0.0.1:8000 -> internal Edge Lab API
  postgres        -> no host port
  redis           -> no host port
  workers         -> no host port
```

There are two dedicated hosted networks:

- `dashboard_edge` connects only the public tunnel connector to the dashboard service.
- `dashboard_data` is an internal Docker network connecting only the dashboard/database-role bootstrap to PostgreSQL.

`cloudflared` is not attached to the internal API/database network. The dashboard is not attached to the main API/Redis network. This prevents the tunnel connector from directly addressing PostgreSQL, Redis or `api:8000`, and prevents the hosted dashboard service from directly addressing the internal API.

The hosted launcher creates/rotates a dedicated `edge_dashboard` PostgreSQL login, grants only CONNECT/USAGE/SELECT, and gives future tables SELECT through default privileges. The dashboard never receives the main `edge` database password. The role bootstrap reads `DASHBOARD_DB_PASSWORD` from its process environment inside `psql`; the password is not passed as a `psql` command-line argument.

The owner vault remains outside the VPS. `SIGNER_ENABLED=false` is forced by the launchers. No wallet or signing credential is required for hosted dashboard mode.

## Cloudflare preparation

Use a remotely-managed Cloudflare Tunnel.

1. Add the desired hostname to **Cloudflare Access** first, for example `edge.example.com`.
2. Create an **Allow** policy only for the owner's identity. Do not use an Allow Everyone policy.
3. Prefer a strong identity provider and MFA.
4. Create a remotely-managed Cloudflare Tunnel.
5. Add a published application route for the protected hostname with service URL `http://dashboard:8080`.
6. Do **not** route the tunnel to `api:8000`.
7. Enable **Protect with Access** for the tunnel route when available so the Access token is validated before origin traffic is forwarded.
8. Copy the connector token into uncommitted `deploy/.env.forward` as `CLOUDFLARE_TUNNEL_TOKEN`.

The Compose service injects that connector credential as cloudflared's `TUNNEL_TOKEN` environment variable. The token is deliberately not appended to cloudflared's command line.

The committed example currently pins `cloudflare/cloudflared:2026.7.3`, the upstream release verified when this milestone was prepared. Review upstream release/security notes deliberately before changing that pin instead of silently following `latest` on every restart.

## VPS preparation

Initial target: approximately 4 vCPU, 8 GB RAM and 100+ GB NVMe. Install Docker Engine and the Docker Compose plugin, clone the private repository, then:

```sh
cp deploy/.env.forward.example deploy/.env.forward
chmod 600 deploy/.env.forward
```

Populate at least:

- `POSTGRES_PASSWORD`
- `FORWARD_INGEST_SECRET`
- `DASHBOARD_DB_PASSWORD` — separate from the PostgreSQL admin password, at least 24 characters, using only `A-Z`, `a-z`, `0-9`, `_` and `-`
- `HELIUS_API_KEY`
- `JUPITER_API_KEY`
- `CLOUDFLARE_TUNNEL_TOKEN`

GoPlus remains optional.

The URL-safe character restriction on `DASHBOARD_DB_PASSWORD` is intentional because the value is interpolated into the SQLAlchemy PostgreSQL connection URL. The launcher refuses an invalid or too-short dashboard DB password.

## Start

```sh
sh deploy/start-hosted.sh
```

The launcher:

1. validates required research and hosted secrets;
2. refuses example secrets or `SIGNER_ENABLED != false`;
3. starts the hardened forward-research stack;
4. creates/rotates the SELECT-only dashboard database role;
5. starts the isolated dashboard service;
6. starts Cloudflare Tunnel.

The internal API remains `127.0.0.1:8000`; the dashboard and `cloudflared` publish no host ports.

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
- cloudflared has no host port;
- cloudflared is attached only to `dashboard_edge`;
- dashboard is attached only to `dashboard_edge` and internal `dashboard_data`;
- hosted dashboard uses `edge_dashboard`, not the admin DB role;
- all forward services keep `SIGNER_ENABLED=false`.

From the Internet, the hostname must require Cloudflare Access authentication before the dashboard loads. Do not start the public route first and add Access later.

## Authentication boundary

Dashboard V1 intentionally has no application password in the ASGI service. The Internet authentication boundary is Cloudflare Access, and the dashboard container itself has no host-published port.

If Cloudflare Access is not configured correctly, do not publish/start the tunnel. The internal API must never be used as the tunnel origin as a shortcut.

## Operational boundary

Dashboard V1 can display research NAV, strategy evidence, paper/shadow trades and incidents. It cannot submit orders/swaps, enable signing, move/bridge funds, access the owner vault, promote strategies, or mutate frozen evidence.

Future controls should be separate authenticated, audited operations rather than exposing the internal API.
