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
  -> PostgreSQL (read-only queries by application convention)

VPS-only:
  127.0.0.1:8000 -> internal Edge Lab API
  postgres        -> no host port
  redis           -> no host port
  workers         -> no host port
```

The owner vault remains outside the VPS. `SIGNER_ENABLED=false` is forced by the launchers. No wallet or signing credential is required for hosted dashboard mode.

## Cloudflare preparation

Use a remotely-managed Cloudflare Tunnel.

1. Add the desired hostname to **Cloudflare Access** first (for example `edge.example.com`).
2. Create an **Allow** policy only for the owner's identity. Access is deny-by-default when no Allow policy matches.
3. Prefer a strong identity provider and MFA.
4. Create a remotely-managed Cloudflare Tunnel.
5. Add a published application route for the protected hostname with service URL:

   `http://dashboard:8080`

   Do **not** route the tunnel to `api:8000`.
6. Enable **Protect with Access** for the tunnel route when available so `cloudflared` validates the Access token at the origin boundary.
7. Copy the tunnel connector token into `deploy/.env.forward` as `CLOUDFLARE_TUNNEL_TOKEN`. Never commit the token.

Cloudflare's Docker connector command uses `cloudflare/cloudflared:latest tunnel --no-autoupdate run --token ...`; Edge Lab wraps that pattern in `deploy/compose.hosted.yml`.

## VPS preparation

Minimum starting target remains approximately 4 vCPU, 8 GB RAM and 100+ GB NVMe. Install Docker Engine and the Docker Compose plugin, clone the private repository, then:

```sh
cp deploy/.env.forward.example deploy/.env.forward
chmod 600 deploy/.env.forward
```

Populate at least:

- `POSTGRES_PASSWORD`
- `FORWARD_INGEST_SECRET`
- `HELIUS_API_KEY`
- `JUPITER_API_KEY`
- `CLOUDFLARE_TUNNEL_TOKEN`

GoPlus remains optional.

## Start

```sh
sh deploy/start-hosted.sh
```

The launcher first starts the hardened forward-research stack, then starts the isolated dashboard and Cloudflare Tunnel. The internal API remains bound to `127.0.0.1:8000`; the dashboard container has no host port and is reached only over the Docker network by `cloudflared`.

## Verify on the VPS

```sh
docker compose \
  --env-file deploy/.env.forward \
  -f docker-compose.yml \
  -f deploy/compose.forward.yml \
  -f deploy/compose.solana-forward.yml \
  -f deploy/compose.hosted.yml \
  --profile forward --profile solana ps
```

Expected properties:

- `postgres` and `redis` have no published ports;
- `api` is only `127.0.0.1:8000`;
- `dashboard` has no published host port;
- `cloudflared` is healthy/running;
- all forward services keep `SIGNER_ENABLED=false`.

From the public Internet, the protected hostname should require Cloudflare Access authentication before the dashboard loads.

## Operational boundary

Dashboard V1 is observation-only. It can display aggregate research NAV, strategy evidence, paper/shadow trades and incidents. It cannot:

- submit venue orders or swaps;
- enable the signer;
- move USDC or bridge assets;
- reach the owner vault;
- promote a strategy to live status;
- mutate frozen forward evidence.

Future safe controls should be implemented as separate authenticated operations with explicit audit records rather than broad access to the internal API.
