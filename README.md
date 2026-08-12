# Edge Lab

Edge Lab is the quantitative core for a personal, multi-strategy trading research system.
Milestone 1 intentionally contains **no live trading path**. It establishes the accounting,
risk, experiment, paper-execution, shadow-execution, incident, and health foundations that later
venue adapters must use.

## Safety invariants

- The owner vault is outside this system.
- The signer is disabled by default and the Milestone 1 signer cannot sign even if called.
- Risk decisions fail closed on stale/missing data or degraded dependencies.
- AI output cannot mutate production risk settings.
- Paper and future live execution share one order/fill schema.
- Historical `solana-bot` results are not imported into performance metrics.

## Run tests

```bash
python -m pytest
```

## Run locally

```bash
cp .env.example .env
docker compose up --build
```

API: `http://localhost:8000`

Useful endpoints:

- `GET /health`
- `POST /risk/evaluate`
- `POST /paper/simulate`
- `GET /signer/status`

## Milestone boundaries

Milestone 1 does not include Hyperliquid, Polymarket, Jupiter, Helius, wallet keys, bridge
execution, real order submission, or any GREEN status. See `docs/MILESTONE1.md`.
