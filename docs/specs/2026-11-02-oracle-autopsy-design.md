# Oracle Autopsy — design (v2: Indian market, faster strategies)

Status: DRAFT for owner approval, 2026-11-02. Nothing is built yet. Replaces the v1 draft (ECB FX demo), which the owner rejected as not something he could put money on.

## Why

Madhav wants two things from one project:
1. **Real use:** a tool that looks for trading strategies in the **Indian market** and tells him honestly which, if any, deserve his own money. He wants faster trading than monthly investing: swing trades (days) and intraday.
2. **A showcase:** proof on LinkedIn and X that he builds serious systems end to end and trades for himself.

His old project, `/Users/maddy/CascadeProjects/oracle-trading-system` (December 2025), shows why honesty has to be built in. Verified in its code:
- **Free money:** opening a trade only deducts commission; closing credits the full position value (`environment/oracle_env.py` lines 366-368 and 411), so every round trip on a flat price adds about the whole position to the balance.
- **Understated losses:** `utils/metrics.py` line 66 drops the first value, so 100 → 90 → 80 reports about −11% instead of −20%.
- **Look-ahead leak:** `data/ingestion/main.py` line 267 builds `target_volatility_5d` from the next five days, and `oracle_env.py` lines 156-160 feed any column containing "volatility" to the agent.

## The hard truth this tool starts from

SEBI's studies (research dated 2026-11-02; not independently re-checked): about 7 in 10 individual intraday traders in the cash segment lost money (FY23), and about 91% of individual F&O traders lost money in FY25. Faster trading means more trades, so costs and slippage matter more. The most likely honest output of this tool is "no strategy passed". The tool is built so that a "go" means something when it does come.

## What it is

A local Python tool, `autopsy`, with three parts:

**1. Strategy library (what it looks for).** A fixed, registered list of 8-12 rule-based strategies, each with a small parameter grid, declared before any testing. The owner asked for "day to day trading", so intraday is the primary track:
- **Intraday (primary; 5- or 15-minute bars; every position closed by 3:15 pm):** for example an opening-range breakout, mean reversion to VWAP, first-hour momentum, and gap fade or continuation at the open. Built first.
- **Swing (secondary; hold 1-20 trading days; daily bars):** for example breakout of an N-day high, pullback within an uptrend, and short-term reversal. Built after intraday works, as a comparison: same checks, slower trading.

Universe: liquid NSE stocks (Nifty 100) and liquid equity ETFs. Out of scope for v1: options, futures, options selling, commodities and ML models.

**2. Honesty checks (the core, from the Oracle lessons).** Each returns PASS, FAIL or CAN'T TELL with evidence:
1. **Ledger:** a reference cash-and-shares ledger re-plays every fill using whole shares, next-bar execution and T+1 settlement for delivery trades. Cash + holdings must equal equity at every bar, and a flat-price round trip must lose exactly costs.
2. **Look-ahead:** recompute features on data cut off at time t; any value at or before t that changes is a leak.
3. **Indian costs:** a dated, instrument-specific cost model covering brokerage, STT, exchange charges, SEBI fee, stamp duty, GST and DP charges, with separate intraday and delivery rates. Slippage scenarios are 5/10/25 bps per side for swing and 10/25/50 bps for intraday. Verdicts use results after costs but before tax. Tax is shown on a separate line: intraday profit as business income at the owner's slab rate (an input), and swing profit with 20% short-term capital gains tax. The report shows gross vs net and the slippage level at which the edge vanishes.
4. **Selection without peeking:** strategies and parameters are chosen by walk-forward testing on development data only. The final stretch of data (the last 12 months) is locked: a lock file holds hashes of the data, the chosen strategy and the full trial log. The locked data is opened once, after selection; any further opening is recorded and turns the check to FAIL. The locked data is never used to rank.
5. **Too many tries:** every variant run is logged for life, including abandoned ones. The report shows the trial count and a Deflated Sharpe Ratio as a warning sign, labelled as a heuristic.

**3. Go/no-go and forward test.** Exactly one strategy per speed (at most one intraday and one swing) is picked by walk-forward results on development data, using a selection rule written into the lock file before the locked data is opened. Only those picks are tested on the locked 12 months, and the verdict uses the locked months only. A pick gets **GO** only if all of these hold on the locked data:
- Every gating check is PASS: ledger, look-ahead, lock integrity, and enough data. The Deflated Sharpe Ratio is shown but does not gate.
- Mean daily net profit (after costs at **doubled** slippage, before tax) is above zero, with the lower end of a one-sided 95% block-bootstrap interval above zero.
- It beats a **random-entry baseline**: random trades with the same count, side mix and holding times, run 1,000 times. The strategy's net profit must sit above the baseline's 95th percentile. This is the fair comparison for intraday, which is in cash every night.
- Its Sharpe ratio (daily net returns on the full account) is at least that of buy-and-hold of a Nifty 50 ETF over the same months, shown for context. For intraday this is reported but does not gate.
- Its worst drawdown is within a limit fixed in advance (default 15%).

A check returns CAN'T TELL when there are fewer than 30 trades in the locked months, more than 2% of bars are missing, or a feature function gives different output on identical input. Any CAN'T TELL means **no GO**. Anything that is not GO is **NO-GO**, and the tool says so plainly.

The lock is one-shot for its window. When new data arrives after the lock date, a new lock can be cut over the new data only. The old locked months join the development data, and the lifetime trial log carries over.

**Forward test (phase 2, after v1).** A GO pick enters paper trading using after-the-close replay: each evening the tool fetches that day's candles, works out the trades the strategy would have made, and compares them with what Madhav logged (a CSV he fills in: time, symbol, side, quantity, price he could really have got). Minimum length: 8 weeks for intraday and 3 months for swing. Only then does the report suggest a small, unleveraged pilot with real money, sized by Madhav. Live signals during market hours are out of scope. The tool never places orders.

**The report:** one static HTML file, opened locally. It has a verdict strip, an equity curve against buy-and-hold, gross vs net results, cost sensitivity, the trial log, and a ledger view linked to the chart (click a jump to see the trades behind it).

## Data

- **Upstox API (free)** is the primary source: daily candles back to 2000 and intraday from January 2022. Request limits apply and are handled with caching and backoff. The owner has no broker account yet; Upstox is the chosen broker. He opens the account and generates the free read-only **Analytics Token** (one-year validity, no static IP needed for historical data) under Developer Apps. It is stored in a local file outside the repo, which is never committed and never printed. Until it exists, the tool is built and tested on synthetic data and on manually downloaded NSE daily files (daily bars only, so not intraday validation).
- **NSE bhavcopy / corporate-action downloads** (official, for personal non-commercial use, no scraping) are used to check prices and adjust for splits and bonuses.
- Raw and adjusted prices are stored separately as Parquet snapshots with a hash and download date. Universe membership is taken as of each date where possible; if it can't be reconstructed, the report says the stock list has survivorship bias.
- Intraday history on Upstox starts in January 2022, so there are about three years to develop on and twelve locked months. That's enough for strategies that trade often, but it covers few market regimes; the report says so. Kite Connect (₹500/month, intraday back to 2015) is the upgrade if that proves too short. That's the owner's decision later.
- **No NSE price data is ever committed or published.** The public demo uses synthetic data and the Oracle case study.

## News (added 2026-11-02 at the owner's request)

The owner asked for the fastest news. The research says a retail trader cannot win the headline-speed race: exchange infrastructure latency is in microseconds, and a retail API workflow takes seconds to minutes. So news is used where it can be tested and where speed matters less:

1. **Results-day filter (built first).** Skip day-trading a stock on days with scheduled results or a board meeting, using only notices public before that session. It is compared against the same strategy without the filter and counted as an extra trial.
2. **Three registered event strategies, and no others:**
   1. Long-only continuation after a positive earnings change, entered after publication, held 1, 3 or 5 days.
   2. An opening-range breakout on the day after results, entered after the first completed 15-minute range.
   3. Next-session continuation after a disclosed bulk or block buy. The buyer's identity is never assumed to have been known at the time of the deal.
3. **Event ledger.** Each event is stored with its original document, ISIN, source, the exchange's dissemination time, the local first-seen time, a hash and any revisions, with duplicates across exchanges removed. In backtests a trade can only start after dissemination plus a delay of 1, 5 or 15 minutes, on the next bar. An event with a missing timestamp gives CAN'T TELL.
4. **Sources.** The NSE corporate filings archive (custom date ranges, CSV, received and dissemination timestamps) is downloaded by hand, as NSE prohibits systematic automated collection, and the NSE RSS feeds are used going forward. Upstox's News API (last 7 days only) is used during paper trading only.
5. **Social media (X, Reddit, YouTube via Agent Reach).** It is a read-only "what people are saying" panel during paper trading, labelled untested. It never feeds a GO, because there is no reliable history to test it on. Tip channels are treated with suspicion (SEBI has acted against Telegram and broadcast tip schemes). A trade the owner makes by overriding the strategy on a news hunch does not inherit the strategy's GO.

## Rules this must respect

- SEBI's retail algo framework (in force across brokers from 1 April 2026): v1 places no orders, so it is not an algo under that framework. Any later automation goes through the broker's rules (static IP, order tagging) and is a separate decision.
- Public posts must contain no tips, current holdings, live signals, targets or return promises, and must never offer the strategies or signals to others. Show the engineering, the rejected ideas and the honesty checks, and show results only with a delay and only when data licences allow.

## Showcase

- **Post hook:** "My trading bot could make money on a flat market. The bug was mine. So I built a strategy finder for the Indian market that tries to prove every idea wrong."
- **Video (30-60 s):** the Oracle making fake profit → Autopsy tracing it to one line → the look-ahead catch → the strategy finder rejecting most ideas after Indian costs, using synthetic data or delayed, licence-safe visuals.
- **Repo:** the tool, the planted-bug test suite and the Oracle case can be public; Madhav's data, keys, trial log and chosen strategy stay private.

## Non-goals

No order placement, no broker execution, no options or F&O, no ML, no server or accounts, and no signals service.

## Anti-goals (failure even if it works)

- Showing a GO as a promise of profit, or implying Madhav is a profitable trader.
- A strategy chosen by peeking at the locked data.
- Publishing NSE data, keys, or anything that reads as investment advice.
- Anything touching Nest or Suma work.

## Constraints

- Python 3.11+, CPU only, light memory, on the owner's Mac; $0 running cost apart from an optional data subscription.
- New git repo at `/Users/maddy/B2B/oracle-autopsy`. The old `oracle-trading-system` is not modified; the case study copies the minimum code into `cases/oracle/` with its origin noted. The Oracle case uses a scripted policy on a synthetic flat series, copies only the feature code it needs (TFT `ctx_` columns filled with zeros), and needs no torch.
- Commits are authored by the owner only. No push, PyPI release, GitHub Pages or posting without the owner's explicit approval.

## Design decisions (owner can override)

- Swing plus intraday on liquid NSE cash stocks and ETFs; options, futures and options selling are excluded for v1 (the evidence is worst there, and index F&O contract sizes are ₹15-20 lakh).
- Upstox as the free primary data source.
- Locked final 12 months; 15% drawdown limit; 30-trade minimum; the slippage grids above; minimum paper-trading lengths of 8 weeks and 3 months.
- Sizing in backtests: placeholder capital of ₹2 lakh (an input; the owner sets the real figure). Intraday: one position at a time, using up to 100% of capital, with **no leverage**; short selling is allowed (intraday only). Swing: long only, up to 5 positions at 20% of capital each. Whole shares only, so small capital and per-trade charges are modelled honestly.
- Gating: GO uses the locked months only, results after costs but before tax, a 95% one-sided bootstrap, and a random-entry baseline; tax is reported separately.
- Paper trading is phase 2 and uses after-the-close replay plus a CSV log, not live market-hours signals.
- A static local report instead of a web app.
- Keeping the name Oracle Autopsy, since the Oracle story is the post's hook.

## Left to the builder

Module layout, pandas vs Polars, the charting approach, the exact strategy interface, the cache format details, the bootstrap block length, how the Deflated Sharpe is implemented (tested against known values), and the exact strategy definitions within the families listed.

## Open for the owner

- His starting capital range, which sets per-trade costs such as the ₹15.34 DP charge and whether a ₹500/month data plan makes sense.
- Which broker he will trade with. The cost model defaults to Zerodha-style rates and should be switched to his broker's actual rates.
