**Research one strategy: long-only earnings-reaction continuation, held for 10 trading days.** Its profitability remains **UNVERIFIED**. Indian research documents earnings drift over roughly 64 days; that supports investigating the mechanism, not assuming this shorter price-based version works. [Study](https://www.scirp.net/journal/paperinformation?paperid=88060)

1. **Rules and economics**

   Delivery is more expensive per trade, but holding several days gives a potential drift more room to exceed costs.

   Calculated using [`costs.py`](/Users/maddy/B2B/oracle-autopsy/src/autopsy/costs.py) and the Zerodha rate table, assuming equal buy/sell notionals, one order each and one delivery-sale DP charge:

   | Position notional | MIS round trip | Delivery round trip |
   |---|---:|---:|
   | ₹10,000 | ₹10.63 / **0.1063%** | ₹37.59 / **0.3759%** |
   | ₹20,000 | ₹21.26 / **0.1063%** | ₹59.84 / **0.2992%** |

   These exclude slippage, income tax and subscriptions. Fix base slippage at **10 bps each way**; doubling adds **0.40 percentage points** round trip. Thus ₹10,000 delivery needs approximately **0.776%** just to break even. Rates match the published [Zerodha tariff](https://zerodha.com/charges/).

   **Universe:** point-in-time NIFTY 100 constituents, using archived effective membership dates. Missing delisted histories remain a coverage problem; current constituents backfilled through history cannot establish an unbiased GO.

   **Three inputs:**

   - **Event:** actual quarterly-results publication, from owner-downloaded NSE CSVs and original attachments. Use verified dissemination time plus one minute historically; live eligibility also requires actual receipt. Deduplicate company/quarter; preserve revisions. Missing publication time means ineligible.
   - **Price response:** let D be the first full session opening after event availability. From Kite completed daily candles, require both stock close-to-close return on D > 0 and stock return minus NIFTY 50 return > 0. Intraday-release reactions before D are deliberately omitted.
   - **Regime:** NIFTY 50 close on D exceeds its trailing 200-session simple average. Both price conditions and regime become usable only next session, after completed data are available.

   **Execution:** buy at next session’s 09:20 executable price, with slippage. Rank competing signals by excess return, ties by ISIN. No duplicate position.

   **Sizing:** whole shares, no leverage; quantity is the smaller of 20% account equity/price and 0.25% equity/(2 × ATR20). ATR uses completed sessions through D. Maximum five positions, subject to available cash.

   **Exit:** 09:20 after ten trading sessions, or next session 09:20 after a daily close breaches entry minus 2 × entry ATR. Gaps can exceed planned risk. Morning execution avoids closing-auction fills.

2. **Historical factors worth trusting**

   **Feasible:** Kite prices/index regimes; verified NSE filing/deal timestamps; historical delivery quantity and turnover from downloaded [NSE reports](https://www.nseindia.com/static/resources/historical-reports-capital-market-daily-monthly-archives).

   Delivery percentage = delivered quantity/traded quantity. Use only after publication, never during its measurement session; historical release timing must be established.

   **Conditional:** [FII/DII aggregates](https://www.nseindia.com/reports/fii-dii) need original publication vintages and revision handling. Our first-release archive is **UNVERIFIED**; exclude them. Aggregate flows also cannot identify buying in an individual stock.

   Sector relative strength and VIX are sourceable, but add selection choices; exclude initially. Sector mappings must be historical. [F&O bans](https://www.nseindia.com/static/products-services/equity-derivatives-risk-management-sec-ban) concern derivatives, not a prohibition on buying cash shares; any factor requires the contemporaneous next-day ban file.

   **Not currently credible:** historical news sentiment or analyst earnings surprises. We lack complete timestamped original articles, revision histories and point-in-time consensus. Retrospective LLM labels risk hindsight and training contamination. Price reaction is explicitly a proxy, not measured earnings surprise.

3. **Preregister three configurations**

   - Ten sessions, regime enabled — primary.
   - Twenty sessions, regime enabled.
   - Ten sessions, regime disabled — ablation.

   **Two varied dimensions; three configurations.** Every other constant above is frozen. Changing any rule creates another logged trial.

   Retain all previous trials. Fix slippage rather than selecting its most favourable value. Choose using development walk-forward only; purge boundary-crossing positions. Seal the selected rule, auxiliary data and one untouched final year.

   Preserve every existing gate, including ≥30 trades, positive bootstrap lower bound and beating 95% of 1,000 random runs. Add preregistered longer-block and capital-constrained, regime-matched controls for clustered earnings trades.

4. **Prior and kill conditions**

   **UNVERIFIED subjective prior: 5–15% probability of GO**, conditional on adequate data.

   Main risks: stale anomaly, reaction already exhausted, market-beta exposure, clustered earnings, survivorship, gaps and small-ticket costs.

   Kill this specification after a valid sealed-year failure; do not tune against that year. Incomplete coverage or fewer than 30 trades means **CAN’T TELL**, not evidence of profitability.

5. **Allowance pilot**

   Only after defensible GO and at least eight weeks paper; extend paper if earnings opportunities are sparse. The repo’s swing specification prefers three months.

   Example: ring-fence **₹25,000 that can be lost**, apply identical sizing, no leverage or replenishment. Stop at 5% allowance drawdown, any execution/data integrity failure, or persistent slippage beyond the tested budget.

   Backtest that exact capital first: ₹2,500 delivery positions cost **0.836% before slippage**. Do not enlarge the allowance merely to rescue economics.

   A few weeks can test manual execution and reconciliation; they cannot establish positive expectancy or reliable tail risk.

6. **Required additions**

   Narrow candidate runner; complete event-coverage manifest; historical membership/missing-security audit; sealed index inputs; configurable sizing/stops; dated auction calendar; dividend and tradable-price/share accounting; matched portfolio controls; strategy-specific paper alerts and manual-fill reconciliation.

   The current random baseline permits overlapping unconstrained trades, and the CLI tries broader grids. Both need explicit handling before interpreting results.

No files were edited.