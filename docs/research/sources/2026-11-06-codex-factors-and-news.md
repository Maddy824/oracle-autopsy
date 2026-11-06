**Recommendation: pre-register monthly stock momentum next, conditional on reconstructing historical membership. Keep news as context.** The evidence supports testing this family; it does not establish a profitable five-stock bot. No files were changed.

**A. Indian factor evidence**

My ranking is **momentum first for breadth of evidence, low volatility second, historical alpha third**. Indian ETF trend-following has weaker directly applicable evidence.

| Factor | Evidence and effect size | Out-of-sample interpretation |
|---|---|---|
| **12–1 momentum** | Agarwalla–Jacob–Varma form monthly winners/losers using the preceding 11 months, skipping the latest month. Their updated library reports WML geometric annualized returns of **10.65% since January 1994**, but **−5.53% in 2025**. These are long–short factor returns, not your long-only portfolio. [Methodology](https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/four-factors-India-90s-onwards-IIM-WP-Version.pdf), [data](https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/) | The library revises historical calculations; it is not an immutable live trading record. **Exact 2015–2025 WML performance remains unverified here.** [Revision policy](https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/) |
| **Volatility-adjusted momentum** | NSE’s six-/12-month momentum back-test returned **18.6% versus 12.7% CAGR** from April 2005–August 2020; its last five years returned **13.4% versus 8.4%**. [White paper](https://www.niftyindices.com/docs/default-source/indices/nifty200-momentum-30/nifty200_momentum_30_index_whitepaper_sep_20.pdf) | Index launched **25 August 2020**: earlier results are reconstructed. Its live 2021–2025 CAGR was **19.00% versus Nifty200’s 16.21%**, but 2025 returned **−4.57% versus +9.57%**. [Launch](https://www.niftyindices.com/Press_Release/ind_prs25082020.pdf), [2025 dashboard](https://www.niftyindices.com/Index_Dashboard/Index_Dashboard_DEC2025.pdf) |
| **Low volatility** | NSE selects low trailing one-year volatility, weights inversely to volatility, and rebalances quarterly. Its 2005–May 2018 price-return back-test delivered **17.66% versus 13.66% CAGR**, with volatility **18.18% versus 22.62%**. [Methodology](https://www.niftyindices.com/Factsheet/Nifty100_LowVolatility30.pdf), [white paper](https://niftyindices.com/docs/default-source/indices/nifty-100-low-volatility-30/nifty100_low_vol_30_white_papere020f74c99bc6f449e1fff0400847f3c.pdf) | Launched July 2016. Live 2021–2025 TRI CAGR: **15.92% versus Nifty100’s 14.91%**. Academic findings conflict: one Indian study reports a strong low-volatility premium; another finds high-volatility outperformance. [Dashboard](https://www.niftyindices.com/Index_Dashboard/Index_Dashboard_DEC2025.pdf), [positive evidence](https://papers.ssrn.com/abstract=3635632), [contrary evidence](https://doi.org/10.1016/j.iimb.2017.01.001) |
| **Historical alpha** | Nifty Alpha50 selects high trailing alpha; launched November 2012. Its 2021–2025 TRI CAGR was **21.25% versus Nifty500’s 16.88%**, but 2025 returned **−10.17% versus +7.76%**. [Factsheet](https://www.niftyindices.com/Factsheet/Factsheet_Nifty_Alpha50.pdf), [dashboard](https://www.niftyindices.com/Index_Dashboard/Index_Dashboard_DEC2025.pdf) | A high realized CAGR is not proof of independent alpha after risk, concentration and implementation costs. |

The latest check weakens any “momentum always wins” story: five-year TRI CAGRs through October 2026 were **momentum 7.93%/parent 8.26%; low-volatility 9.13%/parent 7.22%; Alpha50 11.56%/Nifty500 8.81%**. All are index returns before your implementation costs. [NSE dashboard](https://www.niftyindices.com/Index_Dashboard/Index_Dashboard_OCT2026.pdf)

Indian time-series momentum research exists, including 1996–2020 stock portfolios, but it studies long–short strategies. **A robust post-2015, net-cost result for your particular long-only ETF universe is unverified.** [Study](https://iris.unito.it/handle/2318/1911590?mode=complete)

**B. Survivorship: repair the universe first**

**Severity is unquantified, potentially conclusion-changing.** Today’s membership contaminates historical eligibility; restricting those stocks to their actual membership dates still omits historical members absent today. The repo explicitly lacks historical membership. [Repo limitation](https://github.com/Maddy824/oracle-autopsy/blob/main/README.md)

Evaluate the options as follows:

1. **Recommended: reconstruct point-in-time NIFTY100.** Use a dated anchor and every scheduled/ad-hoc change; record announcement and effective dates, ISIN, predecessor/successor identities, mergers and suspensions. Obtain prices for the entire historical union—including removed companies. Reconcile independent snapshots. Missing former constituents must block validation, not silently disappear. NSE provides a press-release archive, but completeness and reuse permission require verification. [Archive](https://www.niftyindices.com/press-release), [licensing restrictions](https://www.niftyindices.com/disclaimer)
2. **ETF-only:** avoids selecting individual future index winners, but selecting today’s surviving ETFs is not automatically survivor-free. Freeze an objectively dated universe. Historical listings: NIFTYBEES **8 January 2002**, JUNIORBEES **6 March 2003**, BANKBEES **4 June 2004**, LIQUIDBEES **16 July 2003**; GOLDBEES **19 March 2007**. [Historical NSE list hosted by Zerodha](https://zerodha.com/z-connect/wp-content/uploads/2012/11/etfs.pdf), [NSE gold listing](https://www.nseindia.com/get-quote/equity/GOLDBEES/Nippon-India-Gold-Bees). Actual continuous Kite coverage, distributions and executable liquidity remain **unverified**.
3. **Alternative:** license constituent history plus delisted-price/corporate-action data. Prefer this if manual reconstruction cannot be reconciled. Vendor completeness and price are **unverified**.

ETF testing also needs instrument-specific costs: the current cost implementation explicitly covers ordinary equities. [Cost model](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/costs.py)

**C. ONE proposed family: monthly cross-sectional momentum**

These are proposed rules, not measured results:

- **Universe:** reconstructed NIFTY100 membership effective at signal close; 253 consecutive valid daily adjusted bars, positive OHLC/volume. Unknown membership or unresolved corporate actions invalidate the affected evaluation.
- **Two variants only:**  
  `M12`: \(C_{D-21}/C_{D-252}-1\).  
  `M12V`: `M12 / sample_std` of the 252 daily log returns ending D.
- **Schedule/ranking:** last NSE session each month; descending score, symbol ascending for ties. Select top five. No absolute-return threshold or regime filter.
- **Exit:** sell holdings outside the selected five at D+1 open. Retain selected holdings without resizing. No stop, profit target or maximum holding period.
- **Entry:** frozen D selection, D+2 open, descending rank; buy selected unheld stocks. Maximum five positions; whole shares; each new purchase capped at 20% opening equity, including fees, and settled cash. Rejected entries expire until next month.
- **Execution:** adverse 20-bps slippage each leg; verified delivery fees; cash earns zero. Missing executable bars must not generate invented fills.
- **Evaluation:** retain four development folds and sealed holdout. Register exactly two trials at one slippage setting; lifetime count becomes eight. Require every fold’s existing gates and a full-engine random baseline matching replacement opportunities, holding schedules, cash and costs. Compare against passive Nifty exposure and a point-in-time universe benchmark.

This needs bounded integration: current unmanaged sizing uses **initial capital**, and a new family does not automatically receive the existing full-portfolio baseline. [Engine](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/engine.py), [walk-forward](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/research/walkforward.py), [baseline](https://github.com/Maddy824/oracle-autopsy/blob/main/src/autopsy/stats.py)

**Planning estimate, unverified:** one–two replacements/month implies approximately **32–64 completed trades per 2.7-year fold**, and **1.68–3.36% annual cost drag** at 20% position sizes and your assumed 0.7% round-trip cost. Without pre-2015 warm-up, the first fold loses roughly one signal year: approximately **20–40 trades**. Thus ≥30 is **not guaranteed**. Insufficient trades means CAN’T TELL; do not manufacture exits to pass.

**D. News and other inputs**

These are source-permission assessments, not blanket legal clearance. Private use does not override explicit restrictions.

| Source | Usable? Terms quote and proposed fetch/archive |
|---|---|
| **Economic Times RSS** | **Conditional yes for personal feed use:** “personal, non-commercial use”; personal storage exception exists. Poll official RSS modestly; retain supplied headline/excerpt unchanged, attribution and link. AI transformation/model use is **not clearly authorized**. [RSS terms](https://economictimes.indiatimes.com/news/economy/rss.cms) |
| **Moneycontrol RSS** | **Not cleared for this archive.** Terms prohibit “make a copy of, store” and automated extraction without written permission. Obtain permission/feed licence; ordinary subscriptions are insufficient evidence. [Terms §4.4](https://www.moneycontrol.com/cdata/termsofuse.php) |
| **Business Standard RSS** | **No automated research archive without permission:** prohibits “cache or archive the Content” and algorithm/AI uses. Store no corpus under ordinary access. [Terms](https://www.business-standard.com/terms-conditions) |
| **RBI releases/policy calendar** | RSS supports “automatic site updates”, but disclaimer says “caching … are prohibited”. Use RSS for discovery and manually maintained calendar facts; durable document archive permission **unverified**. [RSS](https://rbi.org.in/Scripts/rss.aspx), [disclaimer](https://www.rbi.org.in/Scripts/Disclaimer.aspx) |
| **MoSPI CPI/IIP** | **Conditional yes for Category-A government data:** policy permits “commercial or non-commercial purposes” *(translated)* with attribution. Fetch calendar/release files; preserve initial values, reference period, base year and revisions. [Policy](https://www.mospi.gov.in/CopyrightPolicy), [calendar](https://www.mospi.gov.in/uploads/documents/releaseCalender/1779709510470-ADVANCE%20RELEASE%20CALENDAR%202026-27%20Updated%2025.05.2026.pdf) |
| **NSE announcements** | **No unlicensed automated archive:** “systematic or automated data collection” prohibited; also restricts “virtual trading or simulation”. Manual export does not establish backtesting permission. Licensed feed: preserve dissemination time, attachment and corrections. [Terms §§8–9](https://www.nseindia.com/static/nse-terms-of-use) |
| **BSE announcements** | **Unverified:** exchange disclaimer could not be retrieved; no trustworthy quote obtained. Do not substitute BSE Indices’ separate terms. Seek exchange/vendor permission; then archive receipt/dissemination times and original attachments. [Attempted official disclaimer](https://www.bseindia.com/static/about/Disclaimer.aspx) |
| **GDELT** | **Yes, its datasets:** “unlimited and unrestricted use”; attribution/link required. Fetch API results or raw update files; store URLs, discovery timestamps, entities/tone and extraction version—not an assumed licence to publisher articles. [Terms](https://gdeltproject.org/about.html), [downloads](https://gdeltproject.org/data.html) |
| **FII/DII flows** | NSE restrictions above apply. Licensed feed/manual contextual observation pending permission; preserve each provisional vintage, gross buys/sells and market scope. Data are “provisional and subject to change”. [Report](https://www.nseindia.com/reports/fii-dii), [terms](https://www.nseindia.com/static/nse-terms-of-use) |
| **India VIX/Kite** | Private API interface allowed, but terms restrict “build databases, or otherwise create permanent copies”. **Persistent archive clearance unresolved**; obtain written clarification. Then store timestamped observations and freshness. [Terms §§2,4](https://kite.trade/terms/), [unresolved support discussion](https://kite.trade/forum/discussion/16336/permission-for-private-historical-backtesting-and-local-data-storage) |
| **GIFT Nifty** | **Unverified:** readable archive permission/terms quote unavailable. Use a licensed feed only after checking retention rights; preserve contract, expiry, quote time and delay. [Official disclaimer](https://www.nseix.com/disclaimer) |
| **Crude** | **Yes:** free EIA API permits “search, display, analyze, retrieve”. Archive Brent/WTI observations, units and release vintage; distinguish observation date from availability. [API/terms](https://www.eia.gov/opendata/terms-of-service.php) |
| **USD/INR; US yields** | **Yes:** Fed information generally “may be copied and distributed without permission”. Use H.10 releases and H.15/XML; archive release vintages and observation dates. These are published observations, not live quotes. [Terms](https://www.federalreserve.gov/disclaimer.htm), [H.10](https://www.federalreserve.gov/releases/h10/), [H.15](https://www.federalreserve.gov/releases/h15/) |

For permitted archives, I recommend append-only records containing source URL, stated publication time, **first-seen UTC**, ingestion time, revision link, checksum, units and the actual brief/model output.

**Predictive evidence:** RBI-policy research finds announcement-window effects or weak stock-price associations—not a demonstrated tradable multi-month forecast. VIX measures expected volatility, not direction. [IMF research](https://www.elibrary.imf.org/view/journals/001/2022/209/article-A001-en.xml), [NSE definition](https://www.nseindia.com/static/products-services/indices-indiavix-index). Robust net-cost Indian multi-week predictive evidence for these exact news/flow/macro feeds remains **unverified**.

Use them now for event calendars, exposure explanations and freshness-labelled context only. After a year, pre-register a small number of hypotheses and reserve subsequent data for testing; do not treat the archive-building year as untouched validation.

**E. Ranked next two weeks**

1. Resolve archive permissions and audit point-in-time membership/removed-stock coverage.
2. Freeze the two momentum variants and evaluation rules before inspecting strategy returns.
3. Implement membership, warm-up, sizing and matched-baseline support; test timing/settlement.
4. Run development once; preserve the holdout unless every required gate passes.
5. Start permitted archives and a concise context brief. Defer sentiment trading and further short-hold searches.