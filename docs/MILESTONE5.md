# Milestone 5 — Portfolio Allocator & Treasury Proposal Layer

## Scope

Milestone 5 converts independent strategy candidates into a single **research allocation plan**.
It is deterministic, paper/shadow-only, and cannot move money.

The allocator answers:

1. how much of an opportunity could fit inside the authorised working-capital budget;
2. how much planned loss that adds to the portfolio;
3. whether the strategy/venue/correlation bucket has remaining capacity;
4. what working float each venue would need;
5. whether a known low-cost route from the Solana working treasury could cover that gap.

It does **not** answer whether a strategy truly has edge. Candidate expected edge/confidence remain research
inputs that must come from versioned experiments and forward evidence.

## Capital boundary

The allocator receives three distinct quantities:

- portfolio NAV;
- **authorised working capital** already released by the owner for research/automation;
- vault balance, carried only as an untouched audit reference.

The vault is never added to deployable capital and there is no `vault -> strategy` transfer method.
Existing deployed notional is subtracted before new capital is considered, so open exposure cannot be
forgotten when sizing the next candidate.

## Initial research policy

Defaults are deliberately conservative and configurable:

- 40% of authorised working capital remains unallocated;
- aggregate planned open risk cap: 2% NAV;
- planned risk cap per correlation bucket: 1% NAV;
- maximum notional per strategy: 20% NAV;
- maximum notional per venue: 35% NAV;
- venue working-float buffer: 10% above allocated notional;
- minimum rebalance proposal: $25;
- maximum known transfer cost: 0.5% of proposed transfer.

These are research defaults, not permanent production values and not permission for live capital.

## Candidate ordering

The research-priority score is dimensionless:

`expected profit USD × confidence / planned max loss USD`

where expected profit USD is `proposed notional × expected edge`.

This prevents a smaller position from receiving a higher score solely because its dollar loss is
smaller. The score is only a deterministic ordering mechanism; it is not evidence of profitability.

## Hard sizing limits

For each candidate, approved notional is the minimum of:

- requested notional;
- remaining authorised deployable capital after existing positions and reserve;
- remaining venue notional cap;
- remaining strategy notional cap;
- remaining liquidity capacity;
- notional allowed by remaining global planned-risk capacity;
- notional allowed by remaining correlation-bucket planned-risk capacity.

If the candidate is reduced, the decision records `SIZED_DOWN_BY_PORTFOLIO_LIMITS`. If capacity is
zero, the decision is rejected with the binding reason(s).

Correlated strategies cannot bypass portfolio risk by using different names. BTC trend, SOL trend,
and meme exposure can all share `crypto-beta`, for example, and consume the same bucket risk budget.

## Treasury proposals

The home source is `solana_working_treasury`, representing native Solana USDC already released into
the working-capital layer.

Milestone 5 knows only **cost models supplied to the allocation run**. It does not assume current
CCTP, Hyperliquid bridge, Polymarket bridge, gas, or route fees. If a source/destination route has no
known cost model, no proposal is emitted.

Every proposal is persisted with:

- `proposal_only = true`
- `requires_owner_approval = true`
- `executable = false`

There is no CCTP call, bridge call, wallet call, token transfer, private key or signer route in this
milestone.

## Auditability

Every allocation run stores:

- full request/input snapshot;
- exact allocator policy snapshot;
- NAV, authorised capital, untouched vault reference and reserve floor;
- each candidate's strategy/version/venue/instrument/evidence status;
- requested vs approved notional;
- planned loss and ordering score;
- rejection/sizing reasons;
- every treasury proposal and estimated cost.

This makes later performance review able to distinguish strategy failure from allocator/risk decisions.

## API composition

The portfolio router is composed with the existing Edge Lab API through `app.server:app`. A Docker
Compose override switches the API service to that composed entrypoint while leaving all existing venue
workers unchanged.

Endpoints:

- `POST /portfolio/allocate`
- `GET /portfolio/runs/{run_id}`
- `GET /portfolio/treasury/status`

The allocate endpoint rejects `mode=live` unconditionally.

## Safety invariants

- live allocation mode is unsupported and raises an error;
- authorised working capital cannot exceed NAV;
- existing allocated capital cannot exceed authorised working capital;
- vault balance is never a funding source;
- existing global/bucket/venue/strategy exposure counts before new sizing;
- candidate liquidity is a hard ceiling;
- unknown transfer route => no treasury proposal;
- overly expensive transfer route => no treasury proposal;
- every proposal requires owner approval and is non-executable;
- `DisabledSigner` remains the only signer implementation;
- no strategy is promoted to GREEN by allocation.

## Next after Milestone 5

Milestone 6 is the forward research period and evaluation layer:

1. continuously collect venue data;
2. register strategy experiments before evaluation;
3. produce strategy-level calibration/performance reports;
4. test cost/slippage stress cases;
5. compare paper and shadow execution quality;
6. maintain RED/AMBER/GREEN evidence status per strategy;
7. do **not** enable real signing during the research period.
