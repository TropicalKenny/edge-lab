# Milestone 3 — Polymarket Structural Research

## Scope

Milestone 3 adds **public/read-only Polymarket CLOB V2 research**. It does not add authentication,
order signing, API credentials, pUSD custody, bridge execution, order placement, order cancellation,
or a user WebSocket channel.

The goal is to answer one narrow question rigorously:

> Does a mathematically guaranteed payoff relationship remain profitable at an actually executable
> common size after CLOB depth and current per-market taker fees?

## Current Polymarket interfaces targeted

- Gamma API for market/event discovery and resolution metadata.
- `GET /markets/keyset` with cursor pagination (max page size 100).
- CLOB V2 public order books (`/book`, `/books`).
- CLOB V2 market metadata (`/clob-markets/{condition_id}`).
- Public market WebSocket only (`/ws/market`).
- Geoblock endpoint for server-IP observation only; it does not enable trading.

CLOB V1 assumptions are explicitly out of scope. Production moved to CLOB V2 in April 2026.

## Structural strategies

### 1. Binary complete set

For one ordinary binary market, buy an equal number of YES and NO shares only when:

`guaranteed $1 payout per share > executable YES cost + executable NO cost + taker fees`

The analyzer walks both ask books, finds common executable quantities, and evaluates depth
breakpoints rather than using last trade or midpoint prices.

### 2. Standard NegRisk YES basket

For a non-augmented NegRisk event where exactly one outcome resolves YES, buy equal quantities of
all outcome YES tokens only when the executable all-in basket cost is below the $1 payoff.

### 3. Standard NegRisk NO basket

For an N-outcome standard NegRisk event, an equal basket of all NO tokens pays `N - 1` dollars per
share-set at resolution. The scanner tests whether the all-in executable cost is below that payoff.

### Deferred NegRisk structures

- Augmented NegRisk is explicitly deferred until its dynamic market-addition mechanics are modeled.
- Events containing a dynamic/`Other` outcome may be measured for research but are marked
  **ineligible**, because Polymarket documentation warns that the definition of `Other` can change
  as placeholders are clarified.

## Fee model

Fee metadata is not guessed. If a market has fees enabled and its fee schedule cannot be parsed,
the opportunity fails closed.

The platform-fee curve follows the current Polymarket CLOB V2 Python client logic:

`fee per fill = shares × rate × (price × (1 - price)) ^ exponent`

A 2% fee-estimation buffer is applied by default to reduce false-positive edges caused by rounding
or fee-estimation differences. Builder fees are zero because this research system does not attach a
builder code or submit orders.

## Reproducibility

Every scan can persist:

- event title/slug/NegRisk flags;
- resolution source and description;
- market question, condition ID and YES/NO token IDs;
- fee rate/exponent;
- end date;
- full bid/ask snapshot JSON;
- tick size and minimum order size;
- exchange book timestamp/hash;
- opportunity legs, common quantity, gross cost, fees, guaranteed payoff, net edge and eligibility.

This allows a later review to reconstruct why the scanner believed an edge existed.

## Safety invariants

- `PolymarketPublicClient` has no order/cancel/authentication methods.
- Only the public market WebSocket channel is implemented.
- Missing fee schedule => no eligible edge.
- Missing book => no eligible edge.
- Stale book => no eligible edge.
- Partial basket fill is not treated as arbitrage.
- Augmented NegRisk => deferred.
- Dynamic/Other outcome => ineligible.
- No private key, API key, wallet address, pUSD balance, bridge or signer is required.
- `DisabledSigner` remains the only Edge Lab signing implementation.

## Not yet implemented

Milestone 3 does **not** estimate whether an event will happen. Informational probability research is
a separate later strategy and will require forecast calibration, resolution-rule interpretation,
evidence provenance, Brier/log-loss scoring and independent evaluation.

## Next research work after this milestone

1. Run the collector continuously and measure structural opportunity frequency/duration/capacity.
2. Add WebSocket-backed book-state reconstruction and compare it with REST scan detections.
3. Measure quote-to-detection latency and edge decay.
4. Add capital lock-up / annualized return calculations through expected resolution date.
5. Stress detected edges against fee changes and one-tick adverse movement on every leg.
6. Register structural-arbitrage experiments before any GREEN consideration.
