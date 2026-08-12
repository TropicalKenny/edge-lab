# Milestone 4 — Solana Forensic Research & Shadow Quotes

## Scope

Milestone 4 migrates the useful research ideas from the legacy Solana bot into Edge Lab without
migrating its live-wallet, old Jupiter, paper-P&L, or hand-tuned decision architecture.

This milestone is **research-only**. It does not contain a private key, signer, transaction sender,
Jupiter `/execute` call, token buy/sell method, bridge, or live-capital path.

## Source of the research universe

The launch universe comes from **on-chain Solana transactions**, not DEX Screener profiles, boosts,
or search results.

The Helius `transactionSubscribe` worker filters the official Pump/PumpSwap program IDs and persists
Pump creation transactions matching the documented `InitializeMint2` launch pattern. For that launch
pattern, the first parsed account is stored as the creator and the second as the mint.

The full launch stream is persisted. Enrichment is intentionally a deterministic capped sample so
we can collect unbiased forward research data without calling multiple external APIs for every launch.
The sample function is stable by mint hash, and both sample modulus and per-cycle cap are configurable.
Specific mints can still be analyzed on demand through the research API.

## Enrichment sources

### Helius DAS

Used for fungible-token metadata such as decimals, supply, token program, mint authority and freeze
authority. Any cached price field returned by DAS is stored only as metadata and is not used as the
execution price.

### DEX Screener

Used only as enrichment after a mint has already entered the universe from on-chain discovery. The
highest-liquidity Solana pair is used for price/liquidity/volume/transaction-flow features. DEX
Screener does not decide which launches enter the dataset.

### GoPlus

Used as a secondary security signal. A normalized subset is stored together with the complete raw
response. The transfer-fee field is deliberately named `transfer_fee_rate`, not basis points, so the
system does not invent units that the upstream field does not guarantee.

No GoPlus result is authoritative by itself.

## Jupiter Swap V2 shadow execution

`JupiterShadowClient` only requests current Swap V2 `/order` pricing.

- no taker is supplied;
- no wallet address is required;
- the client has no `/execute` method;
- if Jupiter unexpectedly returns a transaction when no taker was supplied, Edge Lab rejects the
  response instead of storing or signing it.

For an enriched mint, the research pipeline can simulate the ability to exit a small configurable
USD notional by converting that notional to token atomic units using the token's observed DEX price
and Helius decimals, then requesting a mint -> native Solana USDC shadow quote.

This tests **exitability**, not profitability.

## Feature philosophy

Milestone 4 stores features, not a BUY/SKIP score. Candidate features currently include:

- launch age;
- liquidity and market cap;
- 5-minute buy/sell momentum;
- sell ratio;
- volume acceleration;
- liquidity/market-cap ratio;
- short-horizon price changes;
- mint/freeze authority signals;
- creator risk signal;
- top-holder concentration field;
- transfer-fee rate;
- executable shadow-exit USD value and price impact;
- explicit missing-data/error indicators.

The old bot's thresholds are hypotheses only. Later experiments must determine whether these fields
have predictive value out of sample.

## Forward labels and leakage prevention

Forward outcomes are stored in a separate table from entry-time features.

The first DEX snapshot **after the on-chain launch** is the observed entry snapshot. Forward horizons
(5m, 30m, 1h, 6h, 24h) are measured from that observed entry timestamp, not from the launch timestamp.
This prevents a late first enrichment from being mislabeled as an earlier return and excludes any
pre-launch/stale snapshot from the label calculation.

The label service does not feed future prices back into feature rows.

## Operational defaults

- full on-chain launch stream persisted;
- deterministic enrichment sample: 1 in 50 mints by default;
- maximum 20 enrichments per cycle;
- minimum 15 minutes between enrichments for the same mint;
- enrichment cycle every 5 minutes;
- $25 default Jupiter shadow-exit notional;
- Solana USDC remains the home treasury/accounting asset, but no treasury transfer is implemented.

The two Solana workers are behind the Docker Compose `solana` profile so they do not start unless the
operator intentionally enables that research profile and provides the required data-service keys.

## Safety invariants

- `SIGNER_ENABLED=false` remains the only supported configuration.
- The global `DisabledSigner` remains the only signing implementation.
- No Solana private key or seed phrase environment variable exists.
- Helius is data-only.
- DEX Screener is enrichment-only.
- GoPlus is secondary enrichment-only.
- Jupiter is quote-only and has no taker/execute path.
- Missing enrichments are recorded explicitly rather than fabricated.
- Forward labels are separate from features.
- No strategy is promoted from RED by this milestone.

## Next research work

1. Run the launch collector long enough to build a representative dataset.
2. Measure missingness and survivorship in each enrichment source.
3. Add creator-history and wallet-graph features from chain-native transaction data.
4. Add holder-cluster/bundling features rather than treating top-holder concentration as sufficient.
5. Record repeated Jupiter shadow-exit quotes to measure exit-liquidity decay and route failure.
6. Register pre-specified forensic experiments with train/validation/untouched holdout windows.
7. Only after forward evidence exists, test trading policies as separate challenger experiments.
