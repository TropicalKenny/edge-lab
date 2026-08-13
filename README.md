# Edge Lab

Edge Lab is a personal multi-strategy quantitative research platform for measuring trading ideas under realistic costs and execution constraints before any real capital is authorized.

**Current mode: paper/shadow research only.**

The owner vault is outside Edge Lab. No current forward-research service has a live wallet/signing path, and the strongest automated evidence result is `GREEN-1_CANDIDATE` — a recommendation for later review, not permission to trade real money.

## Current research engines

- **Hyperliquid funding/carry** — public spot/perp books, funding reconstruction, executable paper/shadow hedges, planned-loss exits.
- **Polymarket structural** — public CLOB V2 binary/NegRisk immediate structural opportunities with delayed executable-book validation.
- **Solana Pump baseline** — chain-native Pump launch universe, forensic/security enrichment and Jupiter Swap V2 quote-only paper/shadow entry/exit observations.

All three write into one immutable forward-evidence journal and are evaluated by the shared RED / AMBER / `GREEN-1_CANDIDATE` framework.

## Safety invariants

- The owner vault is outside this system.
- `SIGNER_ENABLED=false` is mandatory for the forward deployment.
- The included signer implementation is disabled and cannot sign.
- Risk/evidence paths fail closed on stale, missing or inconsistent state.
- AI output cannot silently mutate production risk settings.
- Strategy/version/study assumptions are frozen before forward evidence is collected.
- Data-integrity failures permanently contaminate the affected frozen study.
- No private key, seed phrase, mnemonic or owner-vault credential belongs in the VPS deployment.
- Historical `solana-bot` results are debugging/reference data, not Edge Lab performance evidence.

## Dashboard V1

A responsive read-only research terminal is served by FastAPI:

- `GET /dashboard`
- `GET /dashboard/api/summary`

It shows study NAV, research P&L, evidence state, forward progress, paper trades, shadow observations and incidents. It explicitly reports that live trading, signing, fund movement and vault access are disabled.

For VPS access, Dashboard V1 is designed to sit behind an owner-only **Cloudflare Access + Cloudflare Tunnel** route. PostgreSQL, Redis, workers and future signer services remain private.

## Optional owner alerts

Edge Lab includes a separate Telegram notification worker for critical/data-integrity incidents and evidence-state changes. Delivery is durable/idempotent with bounded retries and does not alter research state when Telegram is unavailable.

Telegram is optional and notification-only. It requires:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

After the private research stack is running:

```sh
sh deploy/start-alerts.sh
```

Then send a one-time channel test using the command printed by the launcher. Telegram credentials are never wallet, signer, venue-order or withdrawal credentials.

## Local development

```sh
cp .env.example .env
docker compose up --build
```

API: `http://localhost:8000`

Dashboard: `http://localhost:8000/dashboard`

Run tests:

```sh
python -m pytest
```

## VPS paper/shadow deployment

The complete handoff is in `docs/DEPLOYMENT_HANDOFF.md`.

Start by generating the real deployment environment without printing its internal secrets:

```sh
sh deploy/init-forward-env.sh
```

Then provide the required external research/tunnel credentials and run the mandatory preflight:

```sh
sh deploy/preflight-forward.sh
```

Start private research:

```sh
sh deploy/start-forward.sh
```

Start the authenticated Dashboard V1 tunnel:

```sh
sh deploy/start-dashboard-tunnel.sh
```

Optional Telegram owner alerts:

```sh
sh deploy/start-alerts.sh
```

Runtime verification:

```sh
sh deploy/verify-forward.sh --with-dashboard
```

After initial evidence heartbeats exist:

```sh
sh deploy/verify-forward.sh --with-dashboard --strict
```

## Evidence before capital

A strategy does not become eligible merely because 90 days pass. The evaluator also requires adequate samples/coverage, realistic cost survival, execution reconciliation, acceptable drawdown and concentration, and no data-integrity failure.

A future micro-live phase — if any strategy earns it — is a separate security milestone with explicitly limited working capital. Nothing in the current repository authorizes live capital.
