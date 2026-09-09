# M6O BTC/UBTC conditional carry shadow study

Registered 9 September 2026 before this study reads live funding or chooses an
entry. Contract: `app/carry_protocol.json`. This is a new research lane; neither
legacy 72-hour validation path nor an existing study is changed.

## Rules and capital

Primary 336 hours (14 days), one 168-hour comparison (7 days). Each has its own
1000 USD hypothetical book. These are alternative experiments, not a combined
2000 USD funded portfolio. Long the actual Hyperliquid UBTC/USDC spot token and
short its BTC perpetual in equal base units. Pin spot market index, token IDs,
names and quote identity at first capture; metadata changes block the lane.
UBTC is explicitly a wrapped exposure, not silently identified as native BTC.
No other token, venue or instrument fallback.

Entry forecast is the lower of the complete last 168-hour and 720-hour realized
funding averages, multiplied by the fixed horizon. A five-minute publication
buffer excludes recently unsettled rates. Require every expected funding hour;
reject historical revisions and future rows. Forecasts are hypotheses, not
future funding receipts. Hourly funding can become negative.

Size at 40% of current book equity divided by oracle price, rounded down to the
shared spot/perpetual size precision. Pay for the spot, reserve 100% of entry
perpetual notional as short collateral, and retain at least 19% of book equity
after entry fees (nominal target 20%). Report returns against the entire book,
including margin and idle reserve. No borrowing or reserve transfer assumption.

Use base tier taker scenarios: spot 7 bps, perpetual 4.5 bps, plus 2 bps adverse
movement on each leg at entry and exit. Walk full book depth rather than use
mid-price fills. Entry requires projected funding minus current executable
round-trip spreads, depth, fees and adverse reserve to exceed 10 bps of hedged
notional. Absolute entry basis must be at most 50 bps. No discount or maker fill
assumption. Book timestamps must be at most ten seconds old, never future, and
pair timestamps within two seconds. Both sides must have sufficient full-size
depth. Actual account fee verification remains outside this account-free study.

Exit at horizon, a 2% book-loss trigger, or a conservative short collateral
ratio at or below 30%. These are triggers, not guaranteed loss limits. Funding
uses realized hourly rates times quantity times the most recent prior sampled
oracle (maximum age 120 seconds). This is an explicitly labeled oracle proxy,
not exact settlement. Never substitute a later price or zero for missing funding.
Unpriceable exits remain open with unknown NAV. Priceable exits with missing
funding preserve the close quote and wait for accounting; they do not invent
realized profit. Monitoring gaps over 180 seconds contaminate the book, trigger
an exit when depth is available, and freeze subsequent entries. Missing oracle
evidence or overdue missing funding also contaminates the book.

## Execution and risk limits

This is a **conditional quote shadow**, not an executable paper broker or claim
that both orders would fill. Public depth is observed without queue position,
order acknowledgments, transaction settlement or wallet access. Baseline P&L
assumes both legs execute at captured depth plus adverse reserve. Failed-second-
leg risk is reported separately: unwind the first leg at current opposite-side
depth with its fees, then apply an additional 100 bps adverse-move scenario.
No invented failure probability is averaged into returns. This scenario is not
a worst-case loss bound: a stranded leg or wrapped-token failure can lose more.
Uncertain joint execution prevents automatic promotion.

Closed trades report realized funding proxy, hedge price P&L including changing
basis, fees, net profit, full-book return and doubled-cost stress on the same
quantities. Observed drawdown uses available net liquidation marks. It is not
tick-level liquidation reconstruction. The margin guard is deliberately not
claimed to reproduce exact venue liquidation or intraminute extremes. USDC is
treated as one USD; stablecoin depeg, wrapper redemption/custody failure and
bridge/withdrawal expenses are not modeled. No cross-venue transfer is assumed.

## Persistence and operations

Worker polls every minute using only the public Hyperliquid info endpoint.
Separate SQLite WAL/FULL synchronous volume `edge-lab-carry-shadow-v1` holds
protocol, pinned identity, immutable funding, prior oracle observations,
transactional books and append-only entry/exit/accounting events. Equal or older
cycle timestamps cannot duplicate accounting. No runtime model fitting or
parameter optimization exists. There are no new credentials, grants or ports.

The existing typed dashboard deployment starts this worker through
`deploy/compose.carry-shadow.yml`. Dashboard mounts only read-only data and
exposes `carry_shadow` separately from portfolio P&L. Missing, blocked and stale
summaries are explicit. Existing trading runners and trend rules are unchanged.
The new research volume is not included in PostgreSQL backups; restore testing
and research-volume backups remain outstanding. Do not delete it on redeploy.

## Review rule

Inspect opening decisions and data integrity immediately after deployment.
Actual 7/14-day outcomes require elapsed forward time unless an earlier guard
exits. Review costs, basis, funding reversals, drawdown, doubled costs and failed-
leg stress before considering any subsequent execution-capable experiment.
No promise of income or promotion follows from an entry, a high projected yield,
or a profitable conditional outcome. Keep this iteration to the registered
primary, comparison and robustness checks; do not chase a winning horizon.

## Official sources checked

- Funding is hourly; cash payment uses oracle price rather than mark price:
  https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding
- Base taker tiers and spot/perpetual fee differences:
  https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees
- Public funding-history, metadata and L2-book contracts:
  https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
