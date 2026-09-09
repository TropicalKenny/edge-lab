# Edge Lab Research and Execution Plan

## Recommendation

Edge Lab should narrow its next build to a simple BTC/ETH trend experiment, followed by a fully accounted funding-carry experiment. Stop routine parameter tuning of the launch-token strategy. Keep its historical evidence and, if its collection costs remain acceptable, its unchanged paper benchmark. Prediction-market arbitrage should stay in data-validation research until synchronized basket execution is credible. Do not start a combined trading portfolio yet.

This revises the implementation order of the earlier strategy review: carry remains a credible economic hypothesis, but trend is the simpler first end-to-end test. The deciding factors are implementation burden, data availability and the speed of obtaining interpretable evidence, not a claim that trend has a higher expected return. The current carry runner accepts only 1–72-hour horizons, so a seven- or fourteen-day study needs deliberate versioning and lifecycle validation rather than an environment-variable adjustment.

The immediate objective should be a reproducible strategy whose results survive unseen data, realistic costs and adverse execution. A positive cumulative paper balance alone is insufficient. Subscription coverage is a later economic test that also depends on capital and recurring expenses; no defensible date or expected monthly income can currently be assigned.

## 1. What the latest audit establishes

The verified 9 September 2026 snapshot at 08:53 UTC contains 32 closed trades in the active exploratory v2 Solana study. Recorded net P&L is −$67.73 on its independent $1,000 starting book. Summed entry allocations are $799.93; this turnover measure is different from starting capital. Every trade has supporting metadata for the quote-value reconciliation, with no missing record and no gross-minus-recorded-cost identity failure.[^1]

| Measure | Verified value | Interpretation |
|---|---|---|
| Closed v2 trades | 32 | A short, dependent forward sample |
| Recorded gross P&L | −$28.81 | Already negative before recorded costs |
| Recorded quote deterioration | $38.92 | Approximately 4.87% of summed allocations |
| Recorded net P&L | −$67.73 | Historical journal result |
| Quote cash-flow P&L | −$64.96 | USD quote proceeds minus USD quote expenditure |
| Difference | +$2.77 | Favorable values clamped by historical decomposition |

The cash-flow diagnostic is a quote USD-value proxy, not evidence of actual transaction settlement. It does not establish network charges, priority fees, failed-transaction expenses or guaranteed fills. Five v2 trades differ under this arithmetic, but the adjustment is far too small to reverse the conclusion. Historical records should remain intact; future accounting changes need a new version and an explicit reconciliation bridge.

The negative gross result also rules out the convenient explanation that fees alone are hiding a profitable signal. Costs are a major problem, but eliminating the recorded $38.92 would still leave the recorded gross loss. This is evidence against allocating more development effort to small parameter changes in the present entry rule. It is not proof that every launch-token strategy is impossible.

The deployed audit is operational infrastructure, not a new source of returns. Its tests passed and its read-only reader was verified against the VPS journal. Longer-horizon carry and liquid-trend challengers remain undeployed. The 72-hour carry validation limit exists in both bootstrap and runner configuration, which is a concrete reason not to treat the proposed horizon extension as already available.[^2]

## 2. Strategy choices and their trade-offs

The most useful question is what repeatable advantage can realistically be measured with this system. For trend, the hypothesis is persistence in price movements; for carry, compensation paid by traders demanding derivative exposure; for structural arbitrage, a price inconsistency between enforceably related claims. None of these mechanisms guarantees an attainable net return. The design must specify who pays, why the difference persists, and what can consume it before execution.

| Candidate | Decision | Main reason |
|---|---|---|
| BTC/ETH spot trend | Build first | Few instruments; clear fills and benchmarks |
| Spot/perpetual carry | Build second | Plausible mechanism; more capital and lifecycle complexity |
| Event-level Polymarket arbitrage | Research only for now | Synchronization and multi-leg execution unresolved |
| Launch-token momentum | Stop routine tuning | Negative gross evidence plus high quote costs |
| Market making / fast scalping | Defer | Queue position, adverse selection and inventory need better simulation |
| AI forecasting / learned allocation | Defer | No demonstrated predictive advantage or adequate independent sample |

Trend research has substantial historical support across liquid markets. Moskowitz, Ooi and Pedersen study 58 futures and forward instruments over more than 25 years, with predictability based on past returns. Liu and Tsyvinski's cryptocurrency research also finds momentum in its historical sample, including weekly Bitcoin results. These findings justify a controlled experiment; they do not validate a particular BTC/ETH rule today or transfer automatically to five-minute launch-token trading.[^3]

The decision to start with spot trend intentionally accepts directional market risk in exchange for simpler accounting. Long/cash signals avoid short borrow, derivative funding and liquidation in the first experiment. They can lose heavily in reversals and underperform buy-and-hold in strong bull markets. Those are measurable trade-offs, and the benchmark must expose them rather than conceal them.

Carry offers a different mechanism and could eventually diversify directional risk. However, a spot hedge does not remove funding reversal, basis changes, collateral fragmentation, venue failure or an imperfect hedge. Two assets named BTC are not necessarily identical claims: Hyperliquid documents that its interface's BTC/USDC can map to UBTC/USDC on HyperCore. Asset identity, backing and redemption assumptions therefore belong in the study definition.[^4]

## 3. First experiment: deliberately simple BTC/ETH trend

Register one primary long/cash rule on each asset before calculating performance. A reasonable engineering choice is to hold the asset when the latest completed daily close exceeds its 90-day simple moving average, and hold cash otherwise. Use a fixed 50% sleeve for BTC and 50% for ETH, with no leverage and no borrowing between sleeves. Ninety days and these weights are proposed experimental choices, not literature-proven optimal parameters.

At 00:05 UTC, evaluate the prior completed UTC day using only available bars. Execute the required change at the first valid subsequent quote, charging the actual chosen venue's taker fee and an independently specified execution allowance. In historical bar-only replay, use the next available bar open plus conservative spread/slippage assumptions, clearly labeled as a lower-fidelity simulation. Do not fill at the close that created the signal.

Keep sleeve capital fixed between signal changes initially, allowing weights to drift. Rebalancing every day introduces a second strategy and extra costs; it should not enter unnoticed through volatility targeting or portfolio normalization. Size each entry from that sleeve's available simulated cash, including fees, and cap all inventory at paid-for holdings. Cash earns zero in the initial simulation so assumed deposit yield cannot create the result.

Pre-register a 180-day moving-average rule as the single slower challenger. A buy-and-hold BTC/ETH portfolio and all-cash portfolio are benchmarks, not additional discoveries. Report the primary result even if the slower rule looks better. Do not search dozens of lookbacks, stops and volatility filters until one equity curve turns green.

Choose the trading venue and asset mapping before performance measurement. The preferred first implementation is a liquid spot venue with public historical data, executable quotes and a clear fee schedule. If Hyperliquid's available spot instruments are used, label the actual token rather than silently substituting ordinary BTC or ETH history. If another venue supplies the price history, call that a signal-prototype test and require a separate deployment-venue execution check.

The official Hyperliquid candle interface returns only the most recent 5,000 candles. That means a 5-minute request cannot supply a multi-year backtest, while daily intervals have a much longer theoretical lookback; actual availability still depends on instrument history. Persist raw responses, verify first/last timestamps, identify missing intervals, and reject accidental duplicates. Never manufacture older venue history by repeating or interpolating recent observations.[^5]

The first trend result should answer three questions: is net return positive after costs; does the rule improve the predeclared return/drawdown trade-off against buy-and-hold; and does the improvement survive modest timing and cost changes? A strategy that only wins because BTC rose is market exposure, not demonstrated timing skill. Market exposure can still be a deliberate choice, but it should be reported as such.

## 4. Second experiment: funding carry with the right denominator

The economic case for carry is credible but frequently overstated. The original authors' December 2025 summary reports roughly 7–8% average annualized basis in specified BTC/ETH futures contracts over its 2019–2024 OKEx sample. An older BIS summary reports a higher average for its study. These are different historical summaries, not current quoted yields or expected returns on total Edge Lab capital. Both emphasize financing and arbitrage constraints.[^6]

Use one 14-day primary horizon and one seven-day comparison, not a continuously optimized horizon. Longer holds spread entry/exit costs over more potential funding receipts, but also increase exposure to adverse funding and basis changes. Thirty days can remain a later extension after persistence, data retention and exit behavior are validated. Existing observation lanes can inform the design without being relabeled completed trades.

At ordinary published base taker rates, Hyperliquid charges 4.5 basis points on perps and 7 on spot. Buying and later selling spot while opening and later closing a perp gives 23 basis points of fees on matched notional. Adding the existing illustrative four-leg reserve of 2 basis points per leg gives 31 basis points. Asset, account and collateral adjustments may differ; these base rates are a planning scenario, not a universal live fee promise.[^7]

For illustration only, constant funding of 0.00125% per hour produces 3 basis points per day on matched notional. Over 14 days that is 42 basis points, leaving 11 after the 31-basis-point budget. On $400 matched notional the remainder is only $0.44, before other costs or basis changes. This scenario demonstrates why lengthening the horizon can improve feasibility while still doing little to cover fixed operating expenses.

Capital accounting is decisive. If $400 buys spot and another $400 supports the short, plus a $200 reserve, then the $0.44 belongs against a $1,000 total capital commitment. It is not a high return on a small margin deposit. The current bootstrap already rejects paired notional above half of initial capital; preserve that conservative interpretation rather than enlarging returns through denominator changes.

Entry selection should use a trailing realized-funding history available at the decision time, not multiply the latest attractive rate by two weeks. A proposed primary rule is to take the lower of trailing seven-day and thirty-day average hourly funding, project it over the fixed horizon, and demand that it exceed documented round-trip costs plus a predeclared 10-basis-point uncertainty margin. This is a conservative hypothesis, not a validated forecaster; missing history means no qualified entry.

Accrue the actual observed hourly funding during the simulated hold. Hyperliquid describes funding payments as hourly; the rate may change and positive funding is paid by longs to shorts. Mark both legs, reserve entry and exit fees, model adverse spread and depth, and record losses from a failed hedge leg. A rate reversal should trigger a predefined reassessment rather than an opportunistic exit rule chosen after observing its outcome.[^8]

Before promotion, test persistent negative funding, widening basis, a sharp upward move in the short leg, an unavailable spot exit, provider outages and restart recovery. Stops do not guarantee fills. Any simulated margin treatment must match the venue's actual collateral mechanics; an economically offsetting spot gain cannot simply be assumed available to meet a separate margin call.

## 5. Prediction markets and other alternatives

Polymarket remains a conditional research option. A recent preprint reconstructs synchronized YES/NO books over seven days and finds them mirrored apart from 20 isolated inconsistencies among more than 308 million messages. It also analyzes event-level conversion opportunities. This supports prioritizing synchronization and contract semantics rather than treating separately fetched quotes as durable arbitrage. The preprint is useful evidence, not an independently reproduced Edge Lab trading result.[^9]

Build event-level basket replay only when all legs can be observed with aligned timestamps and sufficient depth. Validate mutually exclusive and exhaustive outcomes, conversion direction, settlement rules and ambiguous resolution cases. Record executable size and opportunity lifetime. Repeated observations of the same event should contribute one clustered outcome, not hundreds of independent profitable trades.

Costs can overwhelm a small apparent discrepancy. Polymarket currently publishes category-dependent taker parameters and a shares × rate × price × (1 − price) formula. At a crypto rate of 0.07, 100 shares purchased at $0.50 incur $1.75, equal to 3.5% of the purchase amount. Read each market's parameters; category-level assumptions are only defaults for research.[^10]

A batch of fill-or-kill orders is not an atomic basket. Official documentation describes independent acceptance or rejection within a batch. The simulator must therefore model successful first legs, rejected later legs and the cost of unwinding stranded exposure. Maker orders require a fill model; zero maker fees do not mean a posted order will execute.[^11]

Market making is not the easy escape from taker costs. Avellaneda and Stoikov's foundational model explicitly addresses the inventory problem, and its introduction distinguishes inventory risk from informed-trader risk. For Edge Lab, queue position, cancellation delay and fills conditional on subsequent adverse price movement must be modeled before spread income can be trusted. A candle touching a limit is not adequate proof of a fill.[^12]

AI forecasting should also remain deferred. OpenMarket's synchronized prediction-market study reports a null out-of-sample forecasting result and negative simulated trading under its assumptions. That does not prove all models fail, but it is a direct counterexample to the claim that additional data or a more complex model automatically creates profit. Any later model must improve calibration against market probabilities and separately improve executable net P&L.[^13]

Meme research should receive no new routine optimization budget in this cycle. MemeTrans offers useful features for detecting risky migrated launches, but risk classification and reduced losses are not the same as positive trading expectancy. Its migrated-token population also cannot be assumed representative of every new launch. If revisited later, test one point-in-time organic-flow feature against the unchanged baseline, including failures and unroutable tokens.[^14]

## 6. Combining strategies and assessing evidence

Do not assign capital weights to unproven strategies. First keep separate, versioned research books with consistent accounting. Once a family qualifies, simulate the combined portfolio with one actual capital budget, explicit collateral requirements and net instrument exposure. A trend long and a carry short can offset economically, while their studies still compete for the same cash or collateral.

Start with equal capital across qualified families as the transparent portfolio baseline. Compare an equal-risk alternative only when volatility and loss correlations can be estimated from a sufficiently long common history. Measure rolling correlations, simultaneous drawdowns and stress losses; two strategies that usually differ can fail together during a venue or liquidity event. Do not optimize weights from the current few days of sparse observations.

Indicator combinations deserve the same skepticism. Moving averages, return momentum and breakout signals can encode similar price information. A combined score must beat its strongest simple component on unseen data after its extra turnover. The AQR study on factor premia documents substantial out-of-sample attenuation and difficulty earning timing profits after proper lags and costs; complexity should therefore bear the burden of proof.[^15]

For the first research cycle, use exactly three rounds: establish the fixed baseline, test the one preregistered challenger, and perform a robustness/replication round. Each round can contain necessary software fixes, but fixes that change the investment rule create a new recorded trial. Retain failed results and do not replace the test set once its results are disappointing.

Split history chronologically. Use an early development period, a later validation period for the single permitted choice, and an untouched final block. Lock the boundaries before inspecting returns, with at least twelve months in the final block if venue history permits. If history is shorter, say that validation is insufficient rather than inventing coverage. Carry labels need purging around boundaries for overlapping holding periods.

An unseen block is necessary but does not eliminate selection bias. The Deflated Sharpe Ratio addresses multiple testing and non-normal returns; apply such corrections using a disclosed trial count rather than treating the best ordinary Sharpe as conclusive. Use daily portfolio returns and block-based uncertainty, not the fiction that every scan or overlapping trade is independent.[^16]

Proposed admission gates are positive net out-of-sample return, no accounting/data-integrity failures, a defensible improvement against the declared benchmark objective, and no sign reversal under doubled modeled variable execution costs. Also remove the largest winning event, shift fills to less favorable valid timestamps and inspect results across distinct subperiods. These are practical research hurdles, not statistical guarantees or live-trading authorization.

## 7. Execution sequence and stopping decisions

First finish the new ledger contract: token quantities, quote-currency debits and credits, separately modeled incremental costs, realized funding, reservations and available capital. Keep quote-value decomposition as a diagnostic. Tests must cover favorable quotes, missing exits, forced losses, partial fills and restarts. The deployed audit already supplies the historical reconciliation needed to compare versions.

Second implement daily data ingestion and the primary BTC/ETH long/cash rule, then run its fixed backtest and untouched holdout. Start forward paper observation only with a versioned configuration and traceable signal-to-order timestamps. At the same time, retain the existing carry observations and document spot/perp identities and available funding history. This is concurrent data collection, not a requirement to build two complex runners simultaneously.

Third build the 14-day carry lifecycle once full capital, realized funding and failure handling are ready. Compare it with the predeclared seven-day version and cash. A zero-trade result can be correct if fees consume expected income. Do not lower its hurdle merely to create activity.

Fourth review the two families together. If neither survives its gates, stop this cycle and report that no usable edge was found. If one qualifies, continue collecting its independent forward evidence. If both qualify, then evaluate a shared-capital portfolio. A 30-day operational review is a useful checkpoint, but cannot establish long-horizon profitability; forward validation may require many months and still end in rejection.

Use existing VPS capacity and public data initially. Do not buy new feeds, models or infrastructure until a specific missing input prevents a defined test. Preserve the original meme evidence, and keep that benchmark running only if its incremental data cost is acceptable; otherwise recommend a documented end to new entries while preserving exits and history. No pause, new experiment or spending change is enacted by this report.

## 8. Profitability and the business objective

Trading profit and operating profit are different. On $1,000, a hypothetical $20 monthly recurring expense requires $240 per year, or 24% of starting capital annually, simply to pay that expense before other overhead. On $5,000 the same expense is 4.8%; on $10,000 it is 2.4%. These are arithmetic hurdles using an illustrative expense, not a subscription-price quote or forecast.

A strategy with modest positive expected return may therefore be scientifically successful but commercially inadequate at small capital. Increasing leverage to force subscription coverage adds loss risk; it does not improve the underlying edge. Before any later capital decision, compare expected dollar profit after all expenses with uncertainty, drawdown and the opportunity cost of maintaining the system.

The recommended decision is to proceed with a bounded, low-cost experiment program, beginning with liquid spot trend and followed by carry. The alternative is to keep Edge Lab solely as a research and engineering project if the evidence never supports an income role. The current evidence does not justify treating it as a self-funding business, and no amount of repeated tuning should make that label automatic.

## Sources

[^1]: Edge Lab. [Verified cost audit](https://github.com/TropicalKenny/edge-lab/blob/8b3100dfbd74f39b5cb317ac6edf8c511bdd73bc/docs/research/cost-audit-20260909.json). 9 September 2026, 08:53 UTC; private project evidence.
[^2]: Edge Lab. [Carry bootstrap source](https://github.com/TropicalKenny/edge-lab/blob/8b3100dfbd74f39b5cb317ac6edf8c511bdd73bc/app/forward_operations.py). Inspected 9 September 2026; runner configuration also caps at 72 hours in app/hyperliquid_forward.py. [Audit implementation](https://github.com/TropicalKenny/edge-lab/pull/61).
[^3]: Moskowitz, T., Ooi, Y. H., and Pedersen, L. H. [Time Series Momentum](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum). May 2012, author-hosted research summary. Liu and Tsyvinski, [Risks and returns of cryptocurrencies](https://cepr.org/voxeu/columns/risks-and-returns-cryptocurrencies), 6 September 2018, original authors' summary.
[^4]: Hyperliquid. [Info endpoint: asset naming](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint). Official documentation, accessed 9 September 2026.
[^5]: Hyperliquid. [Info endpoint: Candle snapshot](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint). Official documentation, accessed 9 September 2026; 5,000 most recent candles.
[^6]: Todorov, K., Schmeling, M., and Schrimpf, A. [Crypto carry: Market segmentation and price distortions in digital asset markets](https://cepr.org/voxeu/columns/crypto-carry-market-segmentation-and-price-distortions-digital-asset-markets). 22 December 2025. Compared with BIS, [Crypto carry](https://www.bis.org/publications/working-paper-1087-crypto-carry), 4 April 2023 summary.
[^7]: Hyperliquid. [Fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees). Official documentation, accessed 9 September 2026.
[^8]: Hyperliquid. [Funding](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding). Official documentation, accessed 9 September 2026.
[^9]: Gebele, J., Mutzel, T., and Matthes, F. [Executable Arbitrage and Market Efficiency in Prediction Markets](https://arxiv.org/html/2608.00666v1). 1 August 2026 preprint, especially Appendix A; not independently replicated here.
[^10]: Polymarket. [Fees](https://docs.polymarket.com/trading/fees). Official documentation, accessed 9 September 2026.
[^11]: Polymarket. [Place Orders](https://docs.polymarket.com/trading/place-orders). Official documentation, accessed 9 September 2026.
[^12]: Avellaneda, M., and Stoikov, S. [High-frequency trading in a limit order book](https://math.nyu.edu/inmemoriam/avellaneda/HighFrequencyTrading.pdf). Quantitative Finance 8(3), April 2008, pp. 217–224. The PDF publication date supersedes search-engine crawl dates.
[^13]: Young, G. [OpenMarket: A Synchronized Polymarket–Binance Dataset for High-Frequency Prediction-Market Research](https://arxiv.org/html/2607.26245v1). 2026 preprint; null forecasting result under the study's simulation assumptions.
[^14]: Hu, S., Tekin, S. F., Xu, Y., and Liu, L. [MemeTrans: A Dataset for Detecting High-Risk Memecoin Launches on Solana](https://arxiv.org/html/2602.13480v1). 13 February 2026 preprint; migrated-launch population.
[^15]: Ilmanen, A., Israel, R., Lee, R., Moskowitz, T., and Thapar, A. [How Do Factor Premia Vary Over Time? A Century of Evidence](https://www.aqr.com/Insights/Research/Journal-Article/How-Do-Factor-Premia-Vary-Over-Time-A-Century-of-Evidence). 31 October 2021, author-hosted summary; AQR is also an investment manager.
[^16]: Bailey, D. H., and López de Prado, M. [The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf). 2014. Selection bias, multiple testing and non-normal returns.
