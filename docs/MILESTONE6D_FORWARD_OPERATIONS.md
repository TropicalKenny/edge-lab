# Milestone 6D — Forward Research Operations

Milestone 6C can now generate unattended Hyperliquid funding/carry paper + shadow evidence. Milestone 6D adds a deliberately read-only operational surface so the 90-day forward period can be inspected without giving the dashboard or an operator any trading authority.

## Endpoints

- `GET /forward/ops/summary` — active/completed study health, latest NAV, observation age, open positions, evidence counts, and unresolved integrity incidents.
- `GET /forward/ops/incidents` — incident queue, unresolved by default.
- `GET /forward/ops/positions` — persisted Hyperliquid carry position state.

These routes contain **no POST/PATCH/DELETE operations** and do not accept a wallet, account address, API wallet, private key, or venue trading credential.

## Safety boundary

The operations surface reports only database state produced by the research system. It cannot:

- sign;
- submit a Hyperliquid exchange action;
- execute a Jupiter swap;
- move USDC;
- change a strategy status;
- promote RED/AMBER to GREEN;
- authorize working capital;
- resolve or rewrite evidence.

A study with an unresolved `data_integrity=true` incident is surfaced as `contaminated=true`. That condition is visible rather than hidden by later profitable observations.

## Next operational step

Once this milestone is merged, the remaining prerequisite for the actual 90-day run is deployment configuration: PostgreSQL, the public-data collectors, the strict Hyperliquid forward worker, monitoring/backups, and creation of frozen forward studies. Deployment does not enable signing or real capital.
