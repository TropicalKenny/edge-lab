# Edge Lab — VPS Forward-Research Handoff

This is the operational handoff for starting Edge Lab's **paper/shadow forward research** on a VPS. It does not enable live trading.

## What is already implemented

- deterministic accounting/risk core;
- realistic paper/shadow execution framework;
- immutable strategy/experiment/forward-study journal;
- RED / AMBER / GREEN-1-candidate evidence evaluator;
- Hyperliquid funding/carry forward runner;
- Polymarket immediate structural forward runner;
- Solana Pump baseline forward runner using chain-native discovery and quote-only Jupiter requests;
- daily recommendation-only evidence evaluation;
- local PostgreSQL backups;
- read-only hosted Dashboard V1;
- Cloudflare Tunnel + Access deployment overlay;
- fail-closed deployment preflight and runtime verification.

No wallet key, owner-vault credential, live signer, venue order-submission path, bridge transfer, or live-capital authorization belongs in this deployment.

## Recommended VPS baseline

Initial research target:

- Linux VPS;
- 4 vCPU;
- 8 GB RAM;
- at least 100 GB NVMe;
- Docker Engine + Docker Compose v2;
- Git + Python 3 + curl;
- encrypted/off-host backup destination added after first deployment.

A GPU is not required.

## External credentials still required

Only external service credentials block a complete deployment:

1. `HELIUS_API_KEY`
   - Solana transaction/data access.
   - Research credential only.

2. `JUPITER_API_KEY`
   - Jupiter Swap V2 quote-only `/order` calls.
   - Edge Lab does not supply a taker and contains no `/execute` path in the forward runner.

3. `CLOUDFLARE_TUNNEL_TOKEN`
   - Remotely managed Cloudflare Tunnel for Dashboard V1.
   - Configure the owner-only Cloudflare Access application before publishing the hostname.

Optional:

- `GOPLUS_ACCESS_TOKEN` for secondary Solana security enrichment.

Do **not** provide:

- Solana/EVM private key;
- seed phrase/mnemonic;
- hardware-wallet secret;
- owner-vault credential;
- exchange withdrawal key.

## One-time VPS preparation

Clone the private repository on the VPS and enter it:

```sh
git clone <private-edge-lab-repository-url>
cd edge-lab
```

Create the deployment environment with generated internal secrets:

```sh
sh deploy/init-forward-env.sh
```

That command:

- copies the committed environment template;
- generates a random PostgreSQL password;
- generates a separate random forward-ingest secret;
- sets `deploy/.env.forward` to mode `600`;
- never prints the generated secret values.

Edit only the required external credential lines in `deploy/.env.forward`:

```text
HELIUS_API_KEY=...
JUPITER_API_KEY=...
CLOUDFLARE_TUNNEL_TOKEN=...
GOPLUS_ACCESS_TOKEN=...    # optional
```

Do not change `SIGNER_ENABLED` to true.

## Cloudflare dashboard setup

Before publishing the dashboard hostname:

1. Create a Cloudflare Access Self-hosted application for the intended hostname, for example `edge.example.com`.
2. Restrict the Allow policy to the owner identity/approved identity group.
3. Configure MFA/identity-provider requirements as desired.
4. Create a remotely managed Cloudflare Tunnel.
5. Configure its Published Application/Public Hostname service URL as `http://api:8000`.
6. Enable **Protect with Access**.
7. Put only the generated tunnel token in `CLOUDFLARE_TUNNEL_TOKEN` on the VPS.

The hostname is intentionally not stored in Edge Lab code.

## Preflight — mandatory

Run before starting containers:

```sh
sh deploy/preflight-forward.sh
```

The preflight validates secrets, permissions, Docker/Compose, expected services, signer lock, private database ports, loopback-only API exposure and the tunnel's credential isolation.

If the dashboard/tunnel has not been created yet, the private research stack can be checked separately:

```sh
sh deploy/preflight-forward.sh --research-only
```

Do not bypass a failed preflight.

## Start the private research stack

```sh
sh deploy/start-forward.sh
```

This starts the three forward research programmes and the shared evaluator. It still does not start live trading.

## Start authenticated Dashboard V1

After the Access application and tunnel route exist:

```sh
sh deploy/start-dashboard-tunnel.sh
```

The tunnel is separate from the research stack, so dashboard Internet access can be stopped without stopping data collection/research.

## Verify runtime

Basic private stack:

```sh
sh deploy/verify-forward.sh
```

With dashboard tunnel:

```sh
sh deploy/verify-forward.sh --with-dashboard
```

After the workers have produced the required initial heartbeats/evidence:

```sh
sh deploy/verify-forward.sh --with-dashboard --strict
```

Strict verification requires all three frozen studies to pass their existing read-only readiness checks.

## First 24 hours

Do not treat the forward-study clock as trusted immediately after `docker compose up`.

For the first 24 hours:

- confirm all long-running services remain healthy;
- inspect Dashboard V1 for unexpected incidents;
- confirm no data-integrity incident is created;
- confirm NAV observations continue at the expected cadence;
- confirm Hyperliquid funding data and paper/shadow observations reconcile;
- confirm Polymarket structural scans produce delayed execution evidence correctly;
- confirm Solana launch collection, forensic enrichment and quote-only entry/exit observations continue;
- execute a manual PostgreSQL backup;
- restore a backup into a disposable database before depending on unattended operation;
- confirm the forward evaluator writes recommendations without changing `Strategy.status`.

Only after these checks should the stored forward period be treated as operationally trustworthy.

## The 90-day programme

Each strategy is evaluated independently. Time alone cannot make a strategy GREEN.

The default evidence framework also requires sufficient NAV coverage, shadow observations/trades, positive cost-adjusted expectancy, acceptable drawdown, execution reconciliation, low enough profit concentration and no data-integrity failure.

The strongest automated outcome remains:

`GREEN-1_CANDIDATE`

That is an evidence recommendation only. It does not activate a signer or move money.

## Real-money boundary

A future micro-live milestone requires a separate security review and explicit owner action. Even then:

- the owner vault remains outside the VPS;
- only limited working capital can reach execution accounts;
- deterministic risk remains authoritative;
- withdrawals remain owner-controlled;
- AI cannot reveal/import/export wallet keys;
- GREEN does not guarantee profit.
