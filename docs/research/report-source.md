# Edge Lab Strategy Research

## Executive assessment

Edge Lab has a working paper-research engine, but it has not demonstrated a profitable trading strategy. The strongest next direction is to test lower-turnover carry and liquid-asset momentum, with executable prediction-market arbitrage as a separate, conditional research lane. Launch-token momentum should remain an experimental benchmark rather than the presumed source of income. Combining strategies is useful only when their net returns and failure modes differ; combining several losing or highly correlated signals does not create an edge.

The verified paper snapshot at 23:51 UTC on 8 September 2026 shows 30 closed trades in the repaired exploratory Solana cohort and a loss of $64.54 on its independent $1,000 book. Its $935.46 balance includes no open positions. The strict cohort has no trades. These results supersede the earlier six-trade, $8.46-loss snapshot. They are evidence against promoting the present setup, although they are insufficient to prove that every related momentum strategy must fail.[^1]

The deployment repairs are complete: the old cohorts closed, the price-precision fault was corrected, and separate evaluations work. The latest exploratory evaluation is RED and predates ten newer trades; it must not be presented as a current, complete scorecard. Public dashboard email login and backup restore verification remain unfinished. Software reliability, model validity and profitability are three different milestones.[^2]

## 1. What actually produces profit

A strategy needs a repeatable advantage over the price available when it can execute. That advantage may be compensation for providing capital, a forecast that is better than the market's, an enforceable relationship between claims, or liquidity provision. Each has a counterparty, a cost and a failure mode. More indicators, more trades, a higher win rate or an AI-generated explanation are not substitutes for that advantage.

For a directional trade, the basic test is expected net profit = probability of winning × average gross win − probability of losing × average gross loss − expected total costs. A strategy winning 40% of trades can be profitable if winners are sufficiently larger than losers. A strategy winning 90% can lose money if rare losses erase the gains. Position sizing controls exposure to that distribution; it does not turn a negative expectation into a positive one.

There are two separate profit tests. Trading profit is the result after execution, financing and settlement costs. Operating profit also subtracts data, infrastructure and research expenses. For illustration, a $20 monthly expense requires a 2% monthly return on $1,000, 0.4% on $5,000 or 0.2% on $10,000 merely to break even. These are arithmetic hurdles, not achievable-return forecasts or current subscription prices. A small account makes even modest fixed costs important.

The decision rule for Edge Lab should therefore be: identify a causal source of edge, measure it with information available before entry, subtract realistic costs, test it outside the data used to select it, and reject it when the evidence does not survive. An absence of qualified trades can be the correct output.

## 2. Current Edge Lab evidence

The seven study books are independent experiments, each initialized with $1,000 of simulated capital. Their aggregate is not a funded $7,000 portfolio. Pooling old and new cohorts would conceal changes in the experiment and understate the loss in the active exploratory strategy.

| Study | Closed trades | Realized paper P&L | Interpretation |
|---|---:|---:|---|
| Solana exploratory v1 | 9 | −$57.78 | Completed; historical evidence preserved |
| Solana exploratory v2 | 30 | −$64.54 | Active; no open position at capture |
| Solana strict v2 | 0 | $0.00 | Active; security inputs prevent entry |
| Hyperliquid BTC carry | 0 | $0.00 | Active; baseline edge gate rejects candidates |
| Polymarket structural | 0 | $0.00 | Active; no executed paper baskets |
| Other two baseline/retired books | 0 | $0.00 | No evidence of profitability |

The latest ten v2 trades lost $17.24 on a combined $249.97 of entry allocations. Their recorded slippage/quote-deterioration cost totals $12.34, approximately 4.94% of those allocations. Adding that accounting cost back still leaves approximately −$4.90. The immediate problem is therefore both weak gross performance and expensive execution, not costs alone. The ten observations are a recent subset, not the full 30-trade cost history.

The implementation derives this cost from entry and exit quote USD values, while the separate fees field is zero. This is not an audited bill for actual on-chain transactions. It can combine valuation differences, spread and route effects; it must not be relabeled as pure market impact. Future accounting should reconcile actual token quantities and cash flows, identify costs already embedded in the quote, and add only genuinely additional costs. Double-counting fees would be as misleading as omitting them.

Data quality also limits the opportunity set. All 505 strict-v2 candidates examined in the latest 24-hour window carried unknown creator/security or transfer-fee evidence. Repeated market scans are not unique opportunities. Polymarket's research screen reported 112 positive event checks alongside 18,570 stale-book rejections; these are observations, not completed profitable baskets. Hyperliquid's broader research screen found candidates, but its BTC execution baseline still opened nothing. A screen passing and a strategy earning money are distinct events.

## 3. Funding and basis carry

Carry has a clear economic mechanism: traders seeking leveraged directional exposure can pay traders willing to hold the opposite futures exposure and finance a spot hedge. Research by Schmeling, Schrimpf and Todorov links persistent crypto basis to leveraged demand and constraints on arbitrage capital. Their later author summary reports roughly 7–8% average annualized basis for the studied BTC/ETH futures, with substantial variation, using OKEx data from March 2019 to July 2024. That is historical futures-basis evidence, not a forecast for Hyperliquid perpetual funding.[^3]

A spot-long/perpetual-short position attempts to neutralize market direction while receiving positive funding. Its net result still depends on realized funding, changes in the spot/perpetual basis, entry and exit execution, collateral requirements and financing. Unlike a dated future, a perpetual has no fixed maturity guaranteeing convergence on a chosen exit day. Hyperliquid funding is periodic and can change sign; a currently attractive rate is not a locked yield.[^4]

### The horizon problem in Edge Lab

The inspected baseline configuration uses a 24-hour horizon. Its scanner budgets a two-way spot/perpetual fee cost of 23 basis points plus an 8-basis-point slippage reserve: 31 basis points before other financing or failure costs. Those default trading fees match the published standard base rates of 0.045% per perpetual taker trade and 0.070% per spot taker trade, before asset-specific adjustments or discounts.[^5]

At an illustrative constant funding rate of 0.00125% per hour, one day earns only 3 basis points on matched notional. Recovering a 31-basis-point opening-and-closing budget takes roughly 10.3 days if that rate persists and the basis is unchanged. A 24-hour strategy cannot repair this arithmetic by trading more often. The existing research horizons of 7, 14 and 30 days are consequently more relevant hypotheses than relaxing the BTC baseline's entry gate.

The candidate should be ranked by conservative expected net dollars per total committed capital-day. The denominator must include spot cash, derivative margin and a stress buffer, rather than just margin. Higher leverage makes a reported return-on-margin look better while increasing the chance of forced closure. Hyperliquid liquidation uses mark prices, and a profitable spot hedge elsewhere does not automatically supply margin when the short leg needs it.[^6]

**Decision:** give carry first priority for implementation research, preserving the existing baseline. Test a small, preregistered set of liquid, genuinely hedgeable assets and 7/14/30-day holding hypotheses; select using realized funding distributions rather than extrapolating one high rate. Require complete two-leg execution, basis stress and explicit capital usage. Do not buy a token merely to obtain fee discounts, and do not assume maker orders fill because they were posted.

## 4. Momentum on liquid assets

Momentum has stronger empirical foundations than an arbitrary collection of chart indicators. Liu and Tsyvinski found time-series momentum and investor-attention predictability in their historical cryptocurrency sample. Their author discussion includes weekly Bitcoin predictability; it does not establish that a newly launched token can be profitably bought after a five-minute spike and sold thirty minutes later.[^7]

Broader time-series momentum research studies 58 liquid futures and forward contracts across several asset classes and more than 25 years. This supports testing trend persistence as a distinct mechanism, while leaving its current crypto implementation unproven. AQR is both a research publisher and an investment manager, and these historical findings should not be treated as an independent guarantee of future fund or bot returns.[^8]

A useful first liquid-asset hypothesis is a daily-updated directional rule on BTC and ETH, using only completed bars. For example, register one medium-horizon breakout rule and one slower return-sign rule; compare each independently against cash and buy-and-hold. Exact lookbacks are experimental choices, not numbers established as optimal by this report. Size inversely to trailing realized volatility, cap total exposure, and charge funding whenever the simulated instrument is a perpetual.

Trend strategies can struggle in sideways markets and sharp reversals. A volatility or liquidity filter may reduce damage, but every additional filter is another tested hypothesis. A regime model should earn its place by improving unseen results relative to the unfiltered strategy. Retrospectively labeling profitable periods “trending” and avoiding everything else is hindsight, not a deployable signal.

Cross-sectional momentum is an alternative: rank a point-in-time liquid universe and buy relative winners, with a feasible hedge or short side where available. Start later, because listings, survivorship, borrowing and turnover complicate validation. The crypto market/size/momentum factor evidence also warns that several apparently different strategies may be loading on the same risks.[^9]

**Decision:** make simple liquid-asset momentum the second major challenger. It offers a different source of return from carry and a cleaner cost environment than launch-token scalping. Neither family deserves live capital until its own evidence passes.

## 5. Solana launch-token strategies

The current score uses momentum, available volume acceleration, sell pressure and short-window price changes. Those inputs can describe organic demand, but they can also describe coordinated activity. A cross-chain study of 34,988 meme coins found manipulation indicators in 82.8% of its 707 high-return tokens. That percentage applies to the selected high-return subset, not all Solana tokens, and the classification is not proof of fraudulent intent in every individual case.[^10]

Risk detection is useful but different from profit prediction. The MemeTrans preprint analyzes 41,470 migrated Solana launches and more than 200 million transactions, including concentration and bundled-account features. Its reported reduction in losses does not establish positive trading returns. Its migrated-token universe also excludes many launches that never reach migration, creating an applicability limit for an earlier-entry strategy.[^11]

A stronger research design would separate three questions: is the token mechanically sellable; does the demand appear organic; and is the expected move large enough to exceed the executable round-trip cost? Security checks cannot answer the third question. Momentum alone cannot answer the first two. Creator histories must contain only facts known at the time, and missing security evidence must retain its UNKNOWN label.

For cost-aware screening, save an entry quote and a full-size immediate reverse quote at the decision time, then measure the minimum move needed to overcome the round trip. Record quote age and delayed quotes at the actual runner latency. Separately model failed transactions and applicable network charges: Solana documents a base signature fee and optional prioritization fee, including fees charged when execution fails. A quote-only system has not observed transaction inclusion or queue competition.[^12]

**Decision:** do not increase v2 size, loosen security assumptions or keep adding indicators to rescue this loss curve. Preserve it as a small paper benchmark while shifting research effort. A future version should test a specific organic-flow feature and an explicit cost hurdle against the same eligible token set. It should include failed, delisted and unroutable tokens. If those data cannot be collected point in time, the proposed filter cannot be credibly tested.

## 6. Prediction-market arbitrage and forecasting

There is empirical evidence that prediction-market arbitrage has been exploited. Saguillo and co-authors estimated approximately $40 million of extracted Polymarket arbitrage profits in their historical study. That is an estimate across participants and a past market structure, not a return available to every new bot or a claim that any displayed sum below one dollar is tradeable.[^13]

A newer preprint draws the crucial distinction between a payoff identity and an immediately executable conversion. In a seven-day May 2026 check of more than 308 million WebSocket messages, synchronized same-condition YES/NO books were mirrored apart from 20 isolated API inconsistencies. It also reconstructs profitable event-level channels. These findings do not contradict the earlier aggregate estimate: the samples, structures and realization mechanisms differ. They do weaken the case for treating asynchronous YES/NO quotes as durable free money.[^14]

### Costs and execution change the answer

A complete mutually exclusive and exhaustive basket costing $0.97 has a theoretical $0.03 payout surplus per unit before costs. It is attractive only if the entire basket can actually be acquired, its contract semantics guarantee the payout, and all costs plus the time value of locked collateral fit inside that surplus. Similar market titles are not proof that the conditions are complementary.

Current Polymarket documentation makes taker fees category-dependent. The stated formula is shares × fee rate × price × (1 − price); the crypto rate is 0.07. Thus 100 shares bought at $0.50 incur $1.75, or 3.5% of the $50 purchase value, before spread. Makers are not charged trading fees, but an unfilled order earns no spread. Fee parameters must be read for the actual market rather than assumed globally.[^15]

Fill-or-kill is an individual-order property. Polymarket documents independent acceptance or rejection within batches; successful submission of one leg does not guarantee the others. Simulations must include partial-basket exposure, cancellation latency and the cost of unwinding a stranded leg.[^16] Negative-risk conversion can atomically transform a NO position into YES positions in the other outcomes, but that does not make acquisition and disposal of the entire trade atomic. Conversion direction, current outcome set and adapter semantics must be verified.[^17]

**Decision:** prioritize synchronized event-level data and a conservative basket simulator before enabling a challenger. Measure opportunity lifetime, available size, fees, conversion capability and capital lockup. Deduplicate repeated sightings of one event. A higher “opportunities found” counter is not success if executable net profit remains zero.

Forecasting is a separate strategy family. A forecast probability q creates a candidate only when q exceeds the executable purchase price plus costs and a margin for estimation error. Benchmark log loss and Brier score against the market's own contemporaneous probability, then separately test economic returns. OpenMarket's original synchronized Polymarket/Binance study reports a null out-of-sample forecasting result and negative simulated trading after its cost assumptions. That is a useful counterexample to the claim that more data or a predictive model automatically provides an edge.[^18]

## 7. Combining strategies without disguising risk

Combine return streams, not indicator names. Carry, liquid trend and event-level structural trades have different proposed mechanisms, but they can still share exchange, stablecoin, liquidity and technology risks. Several long meme-token rules may simply duplicate exposure to speculative demand. Several election contracts may all fail together under one resolution interpretation.

For directional signals, first express each on a comparable scale using trailing information only. Clip extreme values, estimate reliability on training data and use a simple average as the baseline. Test whether combining signals improves held-out net returns relative to each component. Adding RSI, moving averages and price momentum can overweight one underlying price trend rather than add information.

For strategy allocation, use a separate simulated portfolio with one explicit capital budget. Reconcile overlapping exposures before applying a cap: a carry short may offset a trend long economically, yet both strategies cannot claim unrestricted use of the same collateral. Attribute each strategy's hypothetical contribution and record the executable net position separately. Charge only the costs of the actual portfolio actions; maintain independent research books for fair comparisons.

Start with simple equal risk contributions among strategies that individually pass their tests. Keep cash when none qualifies. Compare the combination against equal capital weighting and the strongest individual strategy. Evaluate rolling return correlations, shared loss days and crisis scenarios; do not optimize weights from two days of sparse trading. A numerical allocation to unproven strategies would manufacture precision the available evidence does not support.

The proposed eventual combination is carry plus liquid trend, with event arbitrage admitted only after executable validation. Meme research remains separate. A signal confidence model can be tested later, once there are enough independent outcomes to estimate it. It should not be an LLM's unsupported confidence score.

## 8. Evidence standards and stopping rules

Record every version, parameter trial, rejected idea and selection criterion. Repeatedly testing variants and publishing only the winner inflates apparent performance. The Deflated Sharpe Ratio addresses selection effects and non-normal returns; the probability-of-backtest-overfitting literature explains why a single attractive backtest or conventional holdout can be misleading after repeated strategy selection.[^19][^20]

Use chronological train, validation and untouched test windows. Fit transformations on training data only. Remove overlapping labels from boundary regions and leave a gap consistent with the holding horizon when necessary. Assess uncertainty with time blocks or event clusters rather than pretending every quote and overlapping position is independent. Keep a final forward period unavailable to tuning.

Each strategy needs a causal baseline and an ablation. Carry must beat its complete fee/financing hurdle. Trend must be compared with cash, buy-and-hold and the simpler trend rule. A meme filter must beat its unfiltered rule on the same eligible universe. An event model must beat the market probability and survive full basket execution. A portfolio must improve the relevant risk/return outcome after additional costs.

The minimum scorecard is gross and net P&L, turnover, realized execution shortfall, fill ratio, maximum drawdown, tail loss, capital utilization, return per capital-day, exposure concentration, data gaps and outcome independence. Report the result excluding the largest winning event as a fragility check. For forecasts, also report calibration by probability bucket, Brier score and log loss. A high win rate alone is not a pass.

The existing 90-day/sample-count and profit-factor gates are policy thresholds, not statistical proofs. They should remain promotion safeguards while research learns faster through replay and falsification. It is unnecessary to wait 90 days to reject a clearly cost-dominated hypothesis; it is equally unjustified to promote a strategy because it reaches a fixed trade count. Reassess at preregistered milestones rather than continuously tuning after each loss.

## 9. Ranked execution plan

| Priority | Work | Evidence required before advancing |
|---|---|---|
| 1 | Reconcile cost and cash-flow accounting | Full-size quotes, explicit additional costs, missing-route cases and reproducible P&L |
| 2 | Carry challenger using existing horizon research | Realized funding, basis stress, full capital denominator and complete two-leg simulation |
| 3 | Simple liquid-asset momentum challenger | Point-in-time bars, frozen rules, cost/funding accounting and unseen-period comparison |
| 4 | Event-level Polymarket simulator | Synchronized books, valid payoff mapping, depth, per-market fees and stranded-leg losses |
| 5 | Solana organic-flow/cost experiment | Point-in-time security and ownership data; measurable improvement over v2 |
| 6 | Combined paper portfolio | Individually qualified strategies, one capital ledger and robust loss-correlation evidence |

The immediate decision is to keep existing evidence intact and stop treating the launch-token bot as the main profit engine. Build the accounting diagnostics first, then the carry and liquid-trend challengers as new versioned studies. This report does not claim those challengers are deployed. The current small paper study continues under its existing rules; no real capital or signing was enabled.

Important limits remain: the available live record is short, quote execution is hypothetical, some market/security inputs are incomplete, and no unseen strategy backtest was performed for this report. Recent preprints provide useful methods and counterexamples but have not been independently reproduced here. Venue fee pages can change. The conclusion is a ranked research decision, not a forecast of monthly income.

## Sources

[^1]: Edge Lab. Live paper-research snapshot, 8 September 2026, 23:51:04 UTC. [Verified snapshot run](https://github.com/TropicalKenny/aurent-design-intelligence/actions/runs/34292437379). Private project evidence; saved snapshot accompanies the repository research record.
[^2]: Edge Lab. [Paper-research reliability repair](https://github.com/TropicalKenny/edge-lab/pull/58) and [execution-price precision repair](https://github.com/TropicalKenny/edge-lab/pull/59), 6 September 2026. Deployed code revision 8b134d2; source/accounting inspection and 262-test verification.
[^3]: Todorov, K., Schmeling, M., and Schrimpf, A. [Crypto carry: Market segmentation and price distortions in digital asset markets](https://cepr.org/voxeu/columns/crypto-carry-market-segmentation-and-price-distortions-digital-asset-markets). CEPR VoxEU, 22 December 2025. Author summary of original research; later sample differs from earlier working-paper versions.
[^4]: Hyperliquid. [Funding](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding). Official documentation, accessed 8 September 2026. Funding mechanism and sign changes.
[^5]: Hyperliquid. [Fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees). Official documentation, accessed 8 September 2026. Standard base rates; actual asset/account adjustments require verification.
[^6]: Hyperliquid. [Liquidations](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/liquidations). Official documentation, accessed 8 September 2026. Mark-price and margin mechanics.
[^7]: Liu, Y., and Tsyvinski, A. [Risks and returns of cryptocurrencies](https://cepr.org/voxeu/columns/risks-and-returns-cryptocurrencies). CEPR VoxEU, 6 September 2018. Original authors' research summary; historical major-coin evidence, not launch-token execution evidence.
[^8]: Moskowitz, T., Ooi, Y. H., and Pedersen, L. H. [Time Series Momentum](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum). Journal of Financial Economics / AQR, May 2012. Historical liquid futures and forward contracts.
[^9]: Liu, Y., Tsyvinski, A., and Wu, X. [Common Risk Factors in Cryptocurrency](https://economics.yale.edu/sites/default/files/2022-10/LiuTsyvinskiWu2019%20COMMON%20RISK%20FACTORS.pdf). Yale-hosted working paper, 15 April 2019. Sample covers 2014–2018; later journal version exists.
[^10]: Mongardini, A. M., and Mei, A. [A Midsummer Meme's Dream: Investigating Market Manipulations in the Meme Coin Ecosystem](https://arxiv.org/html/2507.01963v2). arXiv version 2, 2 January 2026. Observational cross-chain study; subset denominators matter.
[^11]: Hu, S., Tekin, S. F., Xu, Y., and Liu, L. [MemeTrans: A Dataset for Detecting High-Risk Memecoin Launches on Solana](https://arxiv.org/html/2602.13480v1). arXiv preprint, 13 February 2026. Migrated-launch sample and risk-mitigation results.
[^12]: Solana. [Fee Structure](https://solana.com/docs/core/fees/fee-structure). Official documentation, accessed 8 September 2026. Base and prioritization fees; failed transactions.
[^13]: Saguillo, O., Ghafouri, V., Kiffer, L., and Suarez-Tangil, G. [Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets](https://arxiv.org/abs/2508.03474). 5 August 2025. Original historical empirical estimate; not a current attainable-return estimate.
[^14]: Gebele, J., Mutzel, T., and Matthes, F. [Executable Arbitrage and Market Efficiency in Prediction Markets](https://arxiv.org/html/2608.00666v1). arXiv preprint, 1 August 2026, especially Appendix A. Synchronized-book validation and conversion-dependent realizability; not independently replicated here.
[^15]: Polymarket. [Fees](https://docs.polymarket.com/trading/fees). Official documentation, accessed 8 September 2026. Category-dependent formula and fee tables.
[^16]: Polymarket. [Place Orders](https://docs.polymarket.com/trading/place-orders). Official documentation, accessed 8 September 2026. FOK/FAK semantics and independent batch results.
[^17]: Polymarket. [Negative Risk Markets](https://docs.polymarket.com/concepts/negative-risk). Official documentation, accessed 8 September 2026. Atomic conversion mechanics, distinct from multi-order execution.
[^18]: Young, G. [OpenMarket: A Synchronized Polymarket–Binance Dataset for High-Frequency Prediction-Market Research](https://arxiv.org/html/2607.26245v1). arXiv preprint, submitted 28 July 2026; displayed manuscript dated 24 August 2026. Null forecasting result under stated simulation assumptions.
[^19]: Bailey, D. H., and López de Prado, M. [The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf). 2014. Multiple testing, sample length and non-normal returns.
[^20]: Bailey, D. H., Borwein, J., López de Prado, M., and Zhu, Q. J. [The Probability of Backtest Overfitting](https://scholarworks.wmich.edu/math_pubs/42/). Journal of Computational Finance, 2017; earlier working-paper versions. Institutional repository abstract inspected.
