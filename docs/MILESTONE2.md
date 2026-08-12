# Milestone 2 — Hyperliquid Public Research Integration

## Scope

Milestone 2 adds a **read-only Hyperliquid research adapter**. It does not add exchange actions,
wallet keys, API-agent signing, deposits, withdrawals, or live order submission.

### Included

- Public `/info` client for perp/spot market contexts, funding history, L2 books, mids, and
  predicted funding data.
- Mainnet/testnet endpoint selection.
- Parsing of spot metadata by token indices, including non-canonical `@index` markets.
- Timestamped PostgreSQL persistence for perp, spot, and funding snapshots.
- Cost-aware long-spot/short-perp funding/carry candidate analysis.
- Hyperliquid L2 book conversion into the shared Paper Engine V2 order-book model.
- Public WebSocket subscription helper with reconnect/backoff behavior.
- Continuous public market snapshot collector for future VPS deployment.
- Read-only API endpoints for status, snapshot refresh, funding history, carry candidates, and
  paper-book simulation.

## Funding/carry research model

The initial model is intentionally conservative and simple. It estimates:

`expected edge = projected funding - round-trip spot/perp taker fees - slippage reserve`

It does **not** claim the current funding rate will persist. Historical funding stability, basis
behavior, actual L2 execution, hedge error, and adverse-regime stress testing must be added before
any strategy can progress beyond RED/AMBER.

The default baseline fee assumptions correspond to Hyperliquid's current base-tier taker schedule:
4.5 bps for perps and 7 bps for spot. These are research defaults, not hard-coded claims about a
future user's fee tier; live/shadow evaluation must later source the applicable fee tier.

## Safety invariants

- No method in the Hyperliquid client sends `/exchange` actions.
- The signer remains disabled.
- No API wallet or master account address is required.
- Failed/empty market refresh marks Hyperliquid market data unhealthy.
- All real-money status gates remain RED.
- API endpoints are observational/paper-only.

## Next after Milestone 2

Before a funding strategy can be evaluated seriously:

1. accumulate continuous market/funding history;
2. measure funding persistence and reversals;
3. reconstruct spot and perp fills from real L2 depth;
4. model simultaneous-leg timing and hedge slippage;
5. compare carry against idle-USDC opportunity cost;
6. stress basis widening and adverse funding flips;
7. register the first formal funding experiment with an untouched holdout.
