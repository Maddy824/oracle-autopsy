# Oracle Autopsy: evidence and practical trading design

**Research date: 2026-11-05. Every linked source below was accessed on that date.** Publication dates and study periods are stated separately. **UNVERIFIED** means I could not confirm the claim or establish its applicability. Recommendations and capacity assessments are my judgments, not documented trading results.

**Recommendation:** build a small, long-only **post-earnings continuation research and alert tool** first. Use Upstox’s year-long Analytics Token for unattended data, subject to account eligibility; retain Kite for occasional historical downloads and manually authenticated trading. Evidence does **not** yet justify expecting profitable day trading.

The [README](/Users/maddy/B2B/oracle-autopsy/README.md) describes an existing Upstox integration and ORB paper alerts, but no validated live-data operation or strategy GO. The [design](/Users/maddy/B2B/oracle-autopsy/docs/specs/2026-11-02-oracle-autopsy-design.md) already contains suitable event-driven candidates and honesty gates. This was research, not a code audit; no files were changed.

| Decision | Recommendation | Confidence |
|---|---|---|
| First strategy family | Five-day post-earnings continuation | Moderate research rationale; profitability UNVERIFIED |
| Intraday ORB | Retain as a research benchmark | After-cost edge UNVERIFIED |
| Unattended data | Upstox Analytics Token; licensed vendor fallback | High on documented capability |
| Automated Kite login | Do not build around it | Conflicts with broker’s stated login requirements |
| Real-money launch | Only after all existing gates and forward validation | No GO established |

## A. What evidence actually supports making money?

### Regulatory base rates

**Cash intraday:** SEBI’s July 2024 study found **71% of individual intraday traders lost money in FY23**, rising to **80% among those making over 500 trades annually**. Losers incurred transaction costs equivalent to **57% of their trading losses**; winners surrendered **19% of trading profits** to costs. These are ratios to trading losses/profits, not percentages of capital. The study covered ten large brokers, not every trader. [SEBI cash study](https://www.sebi.gov.in/sebi_data/attachdocs/jul-2024/1721818140715.pdf)

**F&O:** over FY22–FY24, **93% lost money**, aggregate losses exceeded **₹1.8 lakh crore**, and only **1% earned over ₹1 lakh after costs** across the period. Individuals paid approximately **₹50,000 crore in transaction costs**; brokerage represented **51%**, exchange fees **20%**. [SEBI, September 2024](https://www.sebi.gov.in/sebi_data/attachdocs/sep-2024/1727086965496.pdf)

**Latest evidence matters:** SEBI’s August 2026 release reports **87.7% losing in FY26**, **₹91,685 crore aggregate net losses**, and approximately **₹25,000 crore transaction costs**. Options accounted for **92% of aggregate losses**. Predominantly option-selling traders were the only strategy group with positive median returns on employed capital, but constituted only around **2% of traders**. This observational result does not establish that switching to selling produces profits. [SEBI FY26 findings](https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787236407005.pdf)

These studies establish difficult base rates; they do not estimate this project’s probability of success or directly evaluate five-day cash strategies.

### Anomaly evidence and retail feasibility

**None of the research below establishes a modern, reproducible, fully costed NSE strategy that this project can simply adopt.** “Abnormal return” is not necessarily an executable return after spreads, brokerage, taxes and market impact.

Capacity below is qualitative: measured rupee capacity is **UNVERIFIED**.

| Family | Evidence quality and after-cost assessment | Point-in-time data and retail capacity |
|---|---|---|
| **Post-earnings drift** | Moderate academic evidence. Sen reports persistence after transaction-cost **proxies**; a later Nifty500 study finds drift over **64 days**, not proof of five-day net profitability. Its retrospective constituent selection also needs scrutiny. [Sen](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1318705); [2018 study](https://file.scirp.org/Html/20-1501629_88060.htm) | Preserve original filing publication time, revisions and comparable EPS. Liquid-stock capacity likely sufficient for small capital; announcement gaps can consume the edge. |
| **Momentum / 52-week high** | Moderate evidence for Indian momentum, usually at **monthly horizons**. Research finds persistent momentum in liquid stocks; transfer to 1–20 days after current costs is **UNVERIFIED**. [2017 paper](https://www.sciencedirect.com/science/article/abs/pii/S1566014117300444); [2023 paper](https://doi.org/10.1016/j.pacfin.2023.102193) | Historical constituents, delistings and corporate actions required. Liquid-stock capacity relatively favourable; turnover matters. |
| **Short-term reversal** | Research associates reversal particularly with illiquidity; that also raises execution concerns. A retail net edge is **UNVERIFIED**. [2023 paper](https://doi.org/10.1016/j.pacfin.2023.102193) | Bid/ask and executable prices needed, not just closes. Capacity weakest where apparent effects are strongest. |
| **Opening-range breakout** | Low-quality, conflicting practitioner evidence. One vendor’s recent Nifty-futures ORB test loses even before costs; it neither validates nor disproves cash-stock ORB. [Vendor test](https://www.quantsapp.com/backtesting/strategies/orb-15min-pct-stop-one-trade) | Timestamped intraday candles and conservative fills required. Liquid instruments offer capacity, but opening execution is critical. |
| **Gap effects** | Reliable, modern NSE after-cost continuation/fade evidence: **UNVERIFIED**. Treat gap direction as a hypothesis, not an edge. | Preserve previous close, corporate actions and opening-session prices. Test delayed fills and unfilled limits explicitly. |
| **FII/DII flows** | Research finds substantial return-to-flow causality, undermining simplistic “follow flows tomorrow” stories. [Indian study](https://www.ide.go.jp/English/Publish/Reports/Dp/180.html) | [NSE daily flows](https://www.nseindia.com/reports/fii-dii) are aggregate/provisional. Archive publication and revisions. Index-scale capacity is ample; predictive edge unproven. |
| **Delivery percentage** | Small-sample research is insufficient for a tradable rule; association does not establish forecasting ability. [Study](https://webfiles.amrita.edu/2021/11/study-on-relationship-between-delivery-quantity-to-total-quantity-traded-and-stock-returns.pdf) | Use completed-session reports only. Delivery percentage does not identify informed buying. Liquidity-dependent capacity. |
| **Bulk/block deals** | Indian evidence shows much reaction on the transaction day, with much smaller next-day returns. [2015 study](https://www.sciencedirect.com/science/article/pii/S1566014115000138) | NSE disseminates reported deal information **after market hours**. Trading earlier using disclosed identities is look-ahead. [NSE rules](https://www.nseindia.com/market-data/large-deals) |
| **Promoter buying / SAST** | A 2026 paper reports longer-horizon insider-trade effects; 1–20-day profitability after costs remains **UNVERIFIED**. [Paper](https://link.springer.com/article/10.1007/s40622-026-00473-3) | Use disclosure time, not transaction date. Separate market purchases from gifts/transfers. Smaller stocks constrain capacity. |
| **F&O ban** | Useful eligibility/risk information; directional alpha **UNVERIFIED**. Current rules use futures-equivalent open interest; old implementations need updating. [NSE Clearing](https://www.nseclearing.in/sites/default/files/2026-01/Recent_changes_in_Equity_Derivative_segment_focusing_on_position_limits%2C_Limit_Monitoring%2C_and_Securities_in_Ban_Period.pdf) | Archive each applicable ban list. Restrictions themselves constrain derivatives execution. |
| **India VIX** | Evidence supports an asymmetric relationship with equity returns, not an automatic forecasting strategy. [NSE working paper](https://nsearchives.nseindia.com/research/content/res_WorkingPaper9.pdf) | Suitable candidate for risk conditioning; use only contemporaneously available values. |
| **Index rebalancing** | Indian studies find temporary/mixed announcement and implementation effects; current after-cost viability **UNVERIFIED**. [2025 research](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5642110) | Preserve announcement versus effective dates. Crowded closing auctions complicate fills and capacity. |
| **Expiry effects** | Older evidence finds volume/volatility effects without dependable reversal. Modern applicability is **UNVERIFIED**. [Study](https://journal.scms.edu.in/index.php/scms/article/view/334) | Historical expiry calendars essential. Treat as execution context, not a standalone signal. |
| **Sector rotation** | Practitioner evidence mostly concerns monthly/quarterly allocation; independent replication and short-swing applicability **UNVERIFIED**. [Practitioner research](https://blog.tradingstudio.finance/sector-momentum-india/) | Historical sector membership and tradable baskets required; constituent liquidity determines capacity. |

Professional firms publicly describe market making, statistical modelling and low-latency infrastructure. Those capabilities are substantially different from a five-minute-candle retail script. Exact proprietary strategies and their net returns remain private. [AlphaGrep](https://alpha-grep.com/about-alpha-grep/); [CRISIL assessment, November 2026](https://www.crisilratings.com/mnt/winshare/Ratings/RatingDocs/AlphaGrepSecuritiesPrivateLimited_November%2002_%202026_RR_409303.html)

Reachable components are slower event research, disciplined execution and risk accounting. I did not verify an audited, reproducible “successful Indian retail algo trader” recipe. Options selling deserves particular caution: premium limits upside while naked calls can have unlimited loss; favourable typical outcomes do not remove tail risk. [Zerodha options explanation](https://zerodha.com/varsity/chapter/sellingwriting-a-call-option/)

## B. Requirements for actual trading usefulness

### Minimum operational requirements — proposed

1. **Data:** immutable raw downloads; publication and receipt timestamps; historical universes; corporate-action handling; missing-bar detection; cross-provider reconciliation. Five-minute OHLC alone cannot establish spread or queue-position fills.
2. **Costs:** date-specific brokerage, STT, exchange charges, GST, stamp duty, SEBI fees and delivery DP charges, plus doubled slippage. Include whole-share rounding and subscription costs in account economics. Use current broker schedules rather than frozen historical assumptions. [Zerodha charges](https://zerodha.com/charges/)
3. **Risk:** initially no leverage; proposed ceilings of **0.25% equity risk per trade**, **1% aggregate planned risk**, and **1% daily loss halt**. Overnight gaps can exceed planned stop risk.
4. **Execution:** unique order intents, duplicate prevention, partial-fill handling, rejection alerts and broker reconciliation. A kill switch must cancel outstanding orders and confirm remaining positions.
5. **Monitoring/journal:** stale-feed alarm, missed-job alerts, signal-to-fill records, skipped trades, actual slippage and daily contract-note reconciliation.
6. **Audit:** preserve data versions, strategy versions, trials, decisions and tax exports.

Cash intraday is generally **speculative business income**. Qualifying delivery equity treated as a capital asset attracts **20% STCG** under the applicable post-July-2024 regime, plus applicable cess/surcharge; frequent delivery activity may instead be business income. Classification and audit obligations require the actual facts, not a universal “all swing trades = STCG” assumption. [Trader taxation](https://zerodha.com/varsity/chapter/taxation-for-traders/); [Income Tax Department](https://www.incometaxindia.gov.in/en/sale-of-shares)

### Retail algo rules in 2026

The February 2025 framework, implementation standards and subsequent extension made compliance mandatory across brokers from **April 1, 2026**. [SEBI framework](https://www.sebi.gov.in/sebi_data/attachdocs/feb-2025/1738665456458.pdf); [implementation timeline](https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf)

For a personal script:

- API orders require identification/tagging and approved authentication.
- NSE’s registration threshold is **10 orders/second**; below-threshold personal strategies still face API controls and generic algo tagging.
- Strategies exceeding the threshold require registration through the broker.
- Static-IP requirements apply to trading API access; OAuth or another permitted mechanism and two-factor authentication apply.
- Black-box algo-provider obligations should not be confused with operating your own private strategy. [NSE implementation standards](https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf)

Kite currently enforces static IP for order endpoints, 10 orders/second, and market protection for API market orders; its data endpoints do not require the trading static IP. [Zerodha implementation notice](https://kite.trade/forum/discussion/15912/preparing-to-comply-with-sebis-retail-algo-rules-static-ip-ratelimits-order-types)

**Interpretation:** alerts followed by independently entering an order in the broker’s normal interface should avoid API-algo registration for that workflow. A human clicking a button that calls `place_order` remains API execution; human involvement is not a blanket exemption.

### Broker comparison

Subscription prices exclude applicable GST; brokerage remains separate. Limits are endpoint-specific ceilings, not guaranteed throughput.

| Broker | Order API / market-data subscription | Selected documented limits |
|---|---|---|
| **Kite** | Orders/account APIs free; live + historical **₹500/month**. [Pricing](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs) | Orders **10/s, 400/min, 5,000/day**; history **3/s**. [Limits](https://www.kite.trade/docs/connect/v3/exceptions/) |
| **Upstox** | Standard APIs free; Analytics Token free. [Pricing](https://upstox.com/trading-api/) | Unregistered orders **10/s, 500/min, 2,000/30min**; standard APIs **50/s**, with longer-window caps. [Limits](https://upstox.com/developer/api-documentation/rate-limiting/) |
| **Dhan** | Orders free; data **₹499/month**. [Pricing](https://dhan.co/support/platforms/dhanhq-api/how-to-access-dhan-api/) | Orders **10/s**; data **5/s**; quote **1/s**; additional caps apply. [Documentation](https://dhanhq.co/docs/v2/) |
| **FYERS** | Standard free; Prime **₹499/month**. [Pricing](https://support.fyers.in/portal/en/kb/articles/how-much-does-fyers-prime-cost-17-7-2026) | Standard data **5/s, 50/min, 5,000/day**; Prime **10/s, 500/min, 500,000/day**. Orders **10/s**. [October 2026 update](https://fyers.in/notice-board/changes-to-fyers-api-rate-limits-and-usage) |
| **Angel SmartAPI** | APIs/data free. [FAQ](https://smartapi.angelone.in/faq) | Combined order operations **9/s**; history **3/s**, with additional caps. [Documentation](https://smartapi.angelone.in/docs) |
| **ICICI Breeze** | API access free. [Product](https://www.icicidirect.com/futures-and-options/api/breeze) | Shared **100 calls/min, 5,000/day** limits constrain practical polling. [Documentation](https://api.icicidirect.com/breezeapi/documents/index.html) |

History coverage also matters: Upstox documents minute history from **January 2022**, so it cannot alone replace the proposed Kite intraday archive back to approximately 2015. Verify instrument-level coverage before treating either as complete. [Upstox historical API](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/)

## C. Solving daily login compliantly

### Kite: technical automation is not documented permission

Kite’s normal access token expires at **06:00 IST the next day**. General personal users do not receive a reusable refresh-token solution. [Authentication documentation](https://kite.trade/docs/connect/v3/user/)

In August 2026, Zerodha staff stated that:

> “a user is required to log in manually at least once a day”

The same response discourages login automation. [Zerodha staff response](https://kite.trade/forum/discussion/16212/batch-automating-kite-login)

The verified regulatory text requires daily API-session logout and two-factor authentication. **An explicit regulatory clause naming Selenium, headless browsers or locally stored TOTP secrets was not verified.** Thus, “SEBI explicitly criminalises headless login” would overstate the evidence; “Zerodha approves unattended password-plus-TOTP login” is also unsupported. [NSE standards](https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf)

### Token alternatives

| Provider | Current documented behaviour |
|---|---|
| **Upstox Analytics** | **One year**, free, read-only; historical data, quotes and WebSockets supported without static IP. Cannot place/modify orders. Some account-data categories require static IP. [Documentation](https://upstox.com/developer/api-documentation/analytics-token/) |
| **Upstox normal** | Expires **03:30 IST**; ordinary trading authentication remains separate. [Documentation](https://upstox.com/developer/api-documentation/get-token/) |
| **Dhan** | Access token **24 hours**. Eligible active web-generated tokens can be renewed; expired tokens cannot. Its 12-month API-key validity is not 12-month access-token validity. Official PIN/TOTP authentication exists. [Documentation](https://dhanhq.co/docs/v2/authentication/) |
| **FYERS** | Current April-2026 guidance requires daily authentication and ends continuous refresh-token sessions. Old “15-day refresh token solves everything” advice is obsolete. [Current guidance](https://support.fyers.in/portal/en/kb/articles/what-are-the-new-sebi-rules-for-retail-algo-trading-from-april-01-2026) |
| **Angel** | Session valid until midnight; PIN/TOTP authentication. Refresh capability does not establish year-long unattended access. [Documentation](https://smartapi.angelone.in/docs) |
| **Breeze** | Session expires at midnight or after 24 hours, whichever comes first; daily generation required. [Session guidance](https://www.icicidirect.com/futures-and-options/api/breeze/article/what-is-a-session-key-and-how-to-generate-it-for-using-breezeapi) |
| **TrueData** | Vendor credentials obtain renewable data tokens; token expires around **04:30 next day**. This is machine authentication, not daily broker-browser login. [Authentication](https://truedataapi.readme.io/reference/post_token); [expiry](https://truedataapi.readme.io/reference/readme) |
| **GDFL** | Subscription access-key authentication documented. Exact key lifetime, relevant package price and permitted uses: **UNVERIFIED** pending quotation. [Documentation](https://docs.globaldatafeeds.in/authentication-request-response-923682m0) |

### Recommended architecture

**Unattended lane:** Upstox Analytics → scheduled data collection → filing ingestion → research/paper ledger → alerts. Obtain the owner’s eligible account first; if onboarding remains blocked, obtain a licensed vendor quotation.

**Authenticated trading lane:** occasional Kite historical backfills and owner-initiated trading sessions. A reminder can open the official login page; it cannot eliminate the owner’s authentication step.

Use official filing feeds and archive receipt times; NSE explicitly warns that RSS updates can be delayed. [NSE RSS](https://www.nseindia.com/static/rss-feed)

On the Mac, store long-lived credentials in **Keychain**, restrict application access, enable FileVault, redact logs and set expiry reminders. Design scheduled jobs to recover missing data after sleep/restarts. Keychain access after reboot can require unlocking, so test recovery rather than promising permanent unattended operation. [Apple Keychain guidance](https://developer.apple.com/documentation/technotes/tn3137-on-mac-keychains)

## D. One strategy, minimal product, honest odds

**Build five-day, long-only post-earnings continuation in a point-in-time liquid-stock universe.** This is a proposed experiment, not a proven after-cost anomaly. Its attraction is lower trading frequency and a clear information event; existing Indian evidence does not prove the selected five-day horizon.

Freeze a simple earnings-improvement definition using information available when the filing arrived. Year-on-year EPS growth is a **proxy**, not an analyst-consensus surprise. Enter no earlier than the next eligible session; preserve consolidated/standalone consistency and original filings.

Minimum product:

- Reliable unattended data and a timestamped event ledger.
- A short candidate list with the source filing and reason.
- Whole-share sizing, cost estimates and portfolio risk checks.
- Conservative paper execution, manual order cards and reconciliation.
- Existing independent ledger, look-ahead tests, sealed year, trial log, deflated-Sharpe assessment and random-entry comparisons.

Match random baselines on capital exposure, universe and calendar conditions. Account for earnings events clustering together. Require a meaningful forward sample; insufficient observations mean **CAN’T TELL**, not GO. Do not repeatedly reopen the sealed year after tweaking rules.

**Probability:** no calibrated success estimate exists. My **subjective, UNVERIFIED estimate is 10–20%** that one preregistered family passes all gates within 12–18 months after usable data is available. That is not a probability of replacing income.

**Kill criteria:** reject the family if the sealed test fails, results depend on unavailable timestamps or surviving constituents, doubled-slippage profitability disappears, or the strategy fails the preregistered random-entry threshold. Pause any later small live pilot when actual execution breaches the cost assumptions or risk limits. Owner unavailability should leave the system producing paper alerts, not improvising unattended execution.

### Core source list

All seen **2026-11-05**; anomaly-specific papers and broker documentation are linked beside their claims above.

- [SEBI cash-intraday study, July 2024](https://www.sebi.gov.in/sebi_data/attachdocs/jul-2024/1721818140715.pdf)
- [SEBI F&O findings, September 2024](https://www.sebi.gov.in/sebi_data/attachdocs/sep-2024/1727086965496.pdf)
- [SEBI FY26 findings, August 2026](https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787236407005.pdf)
- [SEBI retail-algo framework](https://www.sebi.gov.in/sebi_data/attachdocs/feb-2025/1738665456458.pdf) and [NSE implementation standards](https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf)
- [Kite authentication](https://kite.trade/docs/connect/v3/user/) and [Upstox Analytics Token](https://upstox.com/developer/api-documentation/analytics-token/)