**Recommendation: pre-register a weekly-loser reversal family with two holding caps: 5 and 10 sessions.** This is a research candidate, not an established profitable NSE strategy. No files were edited or backtests run.

Repo links below identify locally inspected files; their parity with GitHub is **unverified**. Proposed rules and trade-count estimates are **unverified until tested**.

**1. Evidence and exact proposed rules**

My strongest horizon-matched evidence is de Groot, Huij and Zhou: they study prior-week reversal, including the largest 100 US and European stocks, and show that large-cap selection and reduced turnover materially improve results after costs. Their headline profits concern portfolio strategies, including long–short portfolios—not the expected return of our individual long trades. Their implementation also skips a day after ranking; ours enters next open. This is an adaptation, not a replication. [Paper](https://repub.eur.nl/pub/25718/AnotherLook_2011.pdf)

Indian evidence warrants caution: Chui et al. find momentum concentrated in liquid stocks and reversal in illiquid stocks, but their “short-term” formation periods are **1–3 months**, not five sessions. That neither validates nor directly refutes this weekly hypothesis. I would test weekly reversal before inventing a daily breakout threshold. [Indian study](https://www.sciencedirect.com/science/article/pii/S0927538X23002640)

Freeze the following specification before evaluating returns:

| Component | Fixed rule |
|---|---|
| Family | `weekly_loser_reversal`; variants `h5` and `h10` only |
| Universe | Frozen supplied NIFTY 100 constituent list; exclude NIFTY 50 index. Require 21 consecutive scheduled daily bars through D, valid positive OHLC and volume, and positive ATR20. No backfilling missing history. |
| Features at D close | \(r_5=C_D/C_{D-5}-1\). ATR20 = arithmetic mean of 20 true ranges through D; each true range uses that session’s high, low and preceding close. |
| Signal | Sort eligible stocks by ascending \(r_5\), breaking ties alphabetically by symbol. Among the first \(\lfloor0.20N_D\rfloor\), submit buys only where \(r_5<0\). |
| Priority | Most negative \(r_5\) first; alphabetical ties. Submit all qualifying orders; let portfolio capacity reject excess orders. |
| Entry | D+1 scheduled open, with adverse slippage. Ignore buys for existing holdings; no pyramiding or queued rejected orders. |
| Sizing | Existing whole-share risk sizing, five-position limit, settled-cash constraint and fees. |
| Stop | Freeze at actual slipped entry price minus \(2\times ATR20_D\). A completed close **strictly below** it schedules sale at the following open. No intraday stop-fill assumption. |
| Exit | Stop or holding cap, whichever triggers first. No profit target, trailing stop or signal-based early exit. |
| Holding cap | Entry session E counts as session 1. After session H closes, exit next open: E+H. H is 5 or 10. |
| Regime | None. No earnings, volume-spike or trend filter. |

Five sessions and the bottom quintile anchor the signal to the weekly-reversal literature. Ten sessions tests persistence within the owner’s limit. The negative-return requirement defines an actual loser. ATR20, 2×ATR stops and existing sizing preserve execution conventions; **their optimality is unverified**. [Paper](https://repub.eur.nl/pub/25718/AnotherLook_2011.pdf), [existing strategy](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/strategies/earnings_reaction.py)

**Holding-count trap:** the engine starts age at zero and exits after the triggering close. Therefore use `holding_sessions=4` for H=5 and `9` for H=10. Missing scheduled bars must make the evaluation inconclusive; otherwise “next available open” can exceed the intended cap. [Engine](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/engine.py)

The registry already contains `short_reversal`. Whether its real-data results were previously inspected is **unverified**; check trial history before describing this hypothesis as untouched. Merely renaming an already inspected strategy would not restore independence. [Registry](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/strategies/__init__.py)

**2. Trade frequency and required edge**

These are **planning estimates, not measured frequencies**. Assuming roughly 250 sessions/year, 3–5 occupied positions on average, and approximately one vacant session between positions:

| Variant | Estimated completed trades/year | Approximate trades/2.7-year fold |
|---|---:|---:|
| H=5 | 125–210 | 340–570 |
| H=10 | 70–115 | 190–310 |

Calculation: \(250\times(3\text{–}5)/(H+1)\). Stops can increase turnover; persistent repeat candidates, cash constraints and warm-up can reduce it. Both estimates comfortably exceed 30 per fold, but **actual completed trades control eligibility**. [Execution constraints](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/engine.py), [fold eligibility](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/research/walkforward.py)

Using the repo’s rates, approximately unchanged entry/exit notionals and one DP charge:

\[
\text{break-even gross return}\approx0.2225\%+\frac{₹15.34}{\text{order notional}}\times100\%+0.40\%.
\]

The final term is **20 bps each way**, not 20 bps round trip. Approximate hurdles are **0.78% at ₹10,000; 0.70% at ₹20,000; 0.66% at ₹40,000**. These are before income tax and exclude small compounding differences. [Rate snapshot](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/rates/zerodha_2026-11-02.json), [Zerodha tariff](https://zerodha.com/charges/)

Risk sizing matters: hypothetically, ATR/price=2% gives about ₹12,500 notional at ₹2 lakh equity, requiring roughly **0.75% gross per trade**. A positive gross reversal effect alone is insufficient. [Sizing](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/engine.py)

**3. How it could fool us**

- **Survivorship and corporate actions:** today’s winners exclude failed/deleted constituents; dividend cash flows are absent. Random portfolios share these defects, so passing them does not cure either. Historical membership and dividend-aware validation remain necessary for broader claims. [Known gaps](https://github.com/Maddy824/oracle-autopsy/blob/main/docs/research/2026-11-05-earnings-reaction-build.md)
- **Gaps and unavailable liquidity:** next-open execution captures observed gaps, and the 15% drawdown gate can reject their consequences. A 2×ATR stop is not a guaranteed loss limit; daily bars cannot establish executable liquidity during a price-limit event. [Engine](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/engine.py), [verdict](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/verdict.py)
- **Crowding, decay and correlated trades:** chronological folds and the stationary bootstrap help expose instability and dependence; neither guarantees future persistence. Treat 30 trades as a minimum, not strong evidence. [Walk-forward](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/research/walkforward.py), [statistics](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/stats.py)
- **Costs and search:** retain fixed 10-bps base/20-bps execution, all earlier trials, and best median fold net Sharpe selection. Preserve the sealed year if development fails. Crucially, deflated Sharpe is currently a **descriptive heuristic, not a blocking gate**. [Selection](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/research/walkforward.py), [verdict](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/verdict.py)

**4. Separate future families**

**Long hold:** cross-sectional intermediate momentum—buy stronger 6–12-month performers and hold for months—is my first candidate. Classic evidence concerns 3–12-month holding periods; NSE’s momentum index also uses volatility-adjusted six- and twelve-month returns. Neither supports compressing that effect into a five-day trade. Profitability for this constrained portfolio remains unverified. [Original research](https://doi.org/10.1111/j.1540-6261.1993.tb04702.x), [NSE methodology](https://www.niftyindices.com/indices/equity/strategy-indices/nifty200-momentum-30)

**Intraday:** opening-to-closing momentum: the first half-hour return, including the overnight gap, predicts the final half-hour. Gao et al. provide evidence across liquid ETFs. Five-minute bars can represent those windows, but transfer to individual NSE stocks is **unverified**. Freeze an executable exit window before testing: this repo currently squares off at 15:10, so it cannot silently claim to reproduce the paper’s closing window. [Paper](https://www.sciencedirect.com/science/article/pii/S0304405X18301351), [repo convention](https://github.com/Maddy824/oracle-autopsy/blob/main/README.md)

**5. Minimal implementation changes**

- Add `strategies/weekly_loser_reversal.py`: `VARIANTS`, `data_check()`, `features()`, `signals()`. Register two variants in `strategies/__init__.py`. Use completed-D features directly; the older `swing._daily_features()` adds another session’s lag. [Existing helpers](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/strategies/swing.py)
- **No engine change:** reuse `Signal` with priorities, risk distances and holding values 4/9. Extend `cli._research()` to require index exclusion for this family. [Engine](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/engine.py), [CLI](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/cli.py)
- Extend `walkforward.slippage_grid_for()` to return `(10,)`; otherwise the generic grid creates extra trials. [Function](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/research/walkforward.py)
- Generalize `stats._EarningsPortfolio`/`random_portfolio_baseline()` and dispatch in `verdict.decide()`. Match submitted counts and dates; draw uniformly from history-eligible stocks without the loser filter, using each stock’s ATR, random priority and identical portfolio execution. Preserve exact strategy replay verification. Currently these paths support only earnings. [Statistics](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/stats.py), [verdict](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/verdict.py)

Before real-data evaluation, verify synthetic cases for prefix invariance, ranking, exact 5/10-session exits, rejected orders and baseline replay. Freeze those changes before opening any holdout.