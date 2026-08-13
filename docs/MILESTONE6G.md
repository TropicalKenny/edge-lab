# Milestone 6G — Solana Pump Baseline Forward Study

## Purpose

M6G turns the M4 chain-native Solana launch/forensic pipeline into a genuine forward paper/shadow study that the M6 evaluator can score.

This is deliberately **not** an AI meme-coin picker and not a tuned trading strategy. It is a pre-registered baseline experiment designed to answer a narrower question:

> If every newly observed Pump launch is treated chronologically, and only strict safety + executable-exit gates are applied, does a fixed-small-position policy show any positive forward expectancy after quote deterioration and failed exits?

No historical momentum threshold is optimized to decide entries.

## Frozen lineage

- M4 forensic/source commit: `f26dd56e597c700c9c0783e8cf70d40d224eec80`
- M6G core runner commit: `314e9c158355613f7fccf0a5a5c0e302669c38a6`
- Strategy slug: `solana-pump-safety-baseline`
- Strategy version: `m6g-v1`
- Family: `meme`
- Venue: `solana`
- Instrument: `PUMP_LAUNCH_BASELINE`

Bootstrap registers an immutable strategy version and deterministic experiment, keeps `Strategy.status=red`, freezes the evaluation policy, records initial NAV and rejects later configuration drift for the same study external ID.

## Baseline policy

Default frozen assumptions:

- initial simulated capital: `$1,000`
- simulated entry notional: `$25`
- decision delay after on-chain launch: `5 minutes`
- maximum candidate age: `30 minutes`
- hold horizon: `30 minutes`
- maximum exit grace after horizon: `30 minutes`
- paper-to-shadow delay: `1 second`
- maximum Jupiter quote price impact: `0.05`
- minimum immediate preflight exit recovery: `90%` of entry notional
- maximum concurrent positions: `5`
- maximum new entries per cycle: `3`
- executable NAV interval: `5 minutes`

These values are baseline research assumptions, not claims that they are optimal.

## Candidate universe

The candidate universe remains the full chain-native Pump/PumpSwap launch stream collected from Helius transaction subscriptions. DEX Screener is enrichment only and cannot decide which launches enter the universe.

A launch is not considered before its frozen decision delay. The runner uses the first forensic feature snapshot inside the allowed decision window; future enrichment cannot retroactively change the entry decision.

## Eligibility

A launch can proceed to quote-only entry research only when the decision-time forensic/security evidence is complete and all current baseline gates pass:

- no missing required forensic fields;
- mint authority is not active;
- freeze authority is not active;
- token is not non-transferable;
- creator is not flagged malicious by the stored secondary security signal;
- transfer-fee rate is exactly zero;
- DEX liquidity is positive;
- prior quote-only exit research exists;
- stored exit price impact is within the frozen maximum.

These are safety/exitability gates, not alpha signals. Momentum, holder concentration and volume features are retained for later experiments but do not decide this baseline entry.

## Entry paper/shadow sequence

For an eligible launch:

1. Request a Jupiter Swap V2 `/order` USDC -> token price quote with no taker.
2. Wait the frozen shadow delay.
3. Request the same USDC -> token quote again.
4. Treat the second quote's exact token atomic amount as the simulated acquired position.
5. Request an immediate token -> USDC preflight quote for that exact amount.
6. Open the paper position only if the entry and immediate-exit quotes are complete, within the frozen price-impact limit and the preflight exit recovers at least the frozen ratio.

Jupiter responses containing a transaction are already rejected by the M4 quote client. Edge Lab has no Jupiter `/execute` method and supplies no taker/wallet.

## Position journal and restart safety

M6G does not add a speculative wallet/position store. Open simulated positions are reconstructed from the immutable forward execution journal.

The entry record stores:

- launch signature and mint;
- creator;
- decision/feature identity;
- opened timestamp;
- frozen hold-until timestamp;
- exact shadow-acquired atomic token amount;
- simulated allocated capital;
- entry quote values;
- paper, shadow and preflight quote snapshots.

Operational hardening treats malformed open-position journal metadata as a permanent data-integrity failure. A corrupted entry cannot silently disappear from the sample.

## Exit and missing-route treatment

At the frozen hold horizon:

1. Request a token -> USDC paper quote for the exact journaled atomic amount.
2. Wait the shadow delay when the paper quote is executable.
3. Request the same exit quote again.
4. Close on the delayed shadow quote only when the full amount remains executable.

If no full executable exit is available, the runner retries only inside the frozen exit-grace window.

If that deadline expires, the simulated trade closes with zero recovery. It is **not removed from the dataset**. This intentionally makes dead routes/rugs expensive in the evidence record instead of producing survivorship-biased results.

## P&L accounting

For a normal completed trade:

- gross P&L uses mark-to-mark quote values;
- entry and exit quote deterioration are recorded as slippage;
- net P&L algebraically resolves to delayed executable exit USDC value minus delayed executable entry USDC input.

For a forced no-route exit, net P&L equals the full simulated entry capital loss.

No network transaction is submitted, so M6G does not claim exact on-chain priority/transaction fees. The M6 evaluator still applies its independent cost-stress multiplier before any GREEN candidate recommendation.

## Executable NAV

Open meme positions are not carried at entry value. The operational runner refreshes every open position through a current quote-only token -> USDC executable exit mark.

Simulated NAV is:

`initial capital + closed net P&L + current executable open-position P&L`

If any open position cannot be marked, a fresh NAV is not fabricated and no new risk is added during that cycle. This prevents an unpriceable/rugged token from hiding drawdown behind its original entry value.

## Evidence and promotion

M6G writes normalized M6 records:

- NAV observations;
- entry and exit execution comparisons;
- closed trade outcomes;
- operational/data-integrity incidents.

The existing M6 evaluator treats this as family `meme`. Current default evidence gates include at least 90 forward days, 300 closed meme trades, sufficient NAV/shadow samples, acceptable drawdown, profitability after cost stress, execution agreement and low profit concentration.

Passing those gates can produce only `GREEN-1_CANDIDATE`. It does not change strategy status, enable a signer, authorize capital, or create a wallet.

## VPS operation

The hardened deployment adds `deploy/compose.solana-forward.yml` on top of the existing forward stack.

Required research credentials:

- `HELIUS_API_KEY`
- `JUPITER_API_KEY`

Optional:

- `GOPLUS_ACCESS_TOKEN`

The launcher refuses to start the full forward stack without the required Solana research credentials and continues to force `SIGNER_ENABLED=false`.

Read-only status:

```bash
python -m app.solana_forward_ops status \
  --external-id solana-pump-baseline-m6g-v1 \
  --require-ready
```

The status path checks immutable lineage, initial NAV, frozen config, journal integrity, data-integrity incidents, unresolved critical incidents and NAV freshness.

## Safety boundary

M6G adds no:

- private key or seed phrase;
- Solana wallet address requirement;
- transaction signer;
- Jupiter taker;
- Jupiter `/execute` path;
- arbitrary transfer;
- bridge action;
- live-capital allocation;
- automatic strategy promotion.

The owner vault remains outside the VPS.

## Next milestone

After the Hyperliquid, Polymarket and Solana forward engines are all on main, build Dashboard V1: a mobile-responsive authenticated web interface over the private read-only/control API so the VPS can be monitored from phone/tablet/laptop without exposing PostgreSQL, Redis, workers or signing surfaces.
