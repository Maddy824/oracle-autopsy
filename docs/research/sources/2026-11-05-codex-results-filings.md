**A complete 2015–2026 NSE dissemination-time dataset is not yet verified.** The least-manual compliant route is a licensed historical extract, conditional on sample validation. Public archives contain old results, but timestamp coverage varies.

Checked live on **2026-11-05**; no files edited. Your [importer](/Users/maddy/B2B/oracle-autopsy/src/autopsy/news/nse_filings.py) accepts explicit dissemination timestamps only, interprets timezone-less values as IST, and leaves missing times unset.

1. **NSE announcements and financial results**

   The [announcements page](https://www.nseindia.com/companies-listing/corporate-filings-announcements) exposes company/symbol search, a subject-keyword filter, date presets through **1Y**, Custom dates, and CSV download. Search “financial result” to cover singular/plural subjects; also inspect board-meeting outcomes and earnings releases.

   **Maximum export range, row cap, earliest supported date, and successful historical CSV export: UNVERIFIED.** A 1Y button does not establish a one-year maximum. I inspected pages/indexed records, not a downloaded CSV.

   Historical evidence:
   - [COLPAL, 29-Oct-2015](https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol=COLPAL): results broadcast/received **13:30:41**, dissemination blank.
   - [HINDALCO, 11-Nov-2019](https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol=HINDALCO): results broadcast/received **15:56:55**, dissemination blank.
   - Conversely, the [Financial Results archive for BSE Limited](https://www.nseindia.com/companies-listing/corporate-filings-financial-results?symbol=BSE) contains a filing received **23-Feb-2017 13:19:29**, disseminated **13:22:06**.

   Thus, neither “all 2015–2019 times exist” nor “dissemination began after 2019” is supportable. **Exact publication start date: UNVERIFIED.**

   The separate [Financial Results page](https://www.nseindia.com/companies-listing/corporate-filings-financial-results) offers company/period/date filters, CSV, broadcast timestamps and XBRL links/conversion. Its layout needs an adapter; later XBRL submissions must not be mistaken for the first results release. Complete 2015 XBRL coverage is **UNVERIFIED**.

2. **Other official sources and timing rules**

   [NSE Board Meetings](https://www.nseindia.com/companies-listing/corporate-filings-board-meetings) offers company/date filters and CSV. These notices establish scheduled meetings, not actual results availability or meeting-end time.

   **BSE does publish dissemination times:** a [SEBI order](https://www.sebi.gov.in/sebi_data/attachdocs/jul-2020/1593616533266.pdf) records a BSE announcement at **10-Jul-2017 11:50:35**. The [BSE announcements page](https://www.bseindia.com/corporates/ann.html) returned 403 during research; current scrip-level CSV export, limits and complete 2015 coverage remain **UNVERIFIED**. Its [licensed corporate-data API](https://marketdata.bseindia.com/) is another enquiry route. Preserve BSE provenance; never label its clock “NSE dissemination.”

   The **30-minute rule is not universal today**. [LODR Regulation 30(6)](https://www.sebi.gov.in/sebi_data/attachdocs/apr-2026/1777351317428.pdf) allows three hours when a meeting closes after normal trading hours and more than three hours before the next session, effective **13-Dec-2024**. Regulatory deadlines cannot substitute for observed publication timestamps.

3. **Paid sources**

   | Source | Confirmed; remaining gap |
   |---|---|
   | **NSE Data & Analytics** | [EOD announcements via SFTP: ₹5 lakh/year](https://www.nseindia.com/static/market-data/corporate-data-subscription). The [specification](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/EOD_DATA-Corporate_EODv1.2.pdf) includes minute-resolution announcement datetime. Ten-year backfill and equivalence to the explicit dissemination field: **UNVERIFIED**. |
   | **Global Datafeeds** | [Published corporate-history entitlement is 30 days](https://docs.globaldatafeeds.in/type-of-corporate-data-available-1142925m0). [ReceivedAt/SavedAt](https://docs.globaldatafeeds.in/glossary-923501m0) describe receipt/storage, not explicitly exchange dissemination. Longer negotiated history: **UNVERIFIED**. |
   | **TrueData / Accelpix** | Both advertise announcement APIs: [TrueData](https://www.truedata.in/products/marketdataapi), [Accelpix](https://www.accelpix.com/products/pix-api/). Original dissemination semantics and 2015 backfill: **UNVERIFIED**. Accelpix requires separate commercial/redistribution licensing. |
   | **Trendlyne / Tijori / Screener** | [Trendlyne retains 2015 announcements](https://trendlyne.com/latest-news/BSE-Announcements/1237/SIEMENS/siemens-ltd/?page=95&qstime=1753697485), sometimes date-only. Complete original result timestamps/export rights for all three: **UNVERIFIED**. [Trendlyne](https://trendlyne.com/terms/) requires written authorization for machine-readable databases; [Tijori](https://android.tijorifinance.com/terms-of-use) restricts copying/exploitation; [Screener](https://www.screener.in/guides/terms/) grants personal, noncommercial transitory viewing. |

4. **Owner’s practical sequence**

   **First:** request a one-off licensed extract from NSE Data, with competing vendor quotes. Specify 2015–2026, original dissemination/receipt timestamps, timezone, attachments, revisions, symbol/ISIN history and internal backtesting rights. Require samples from **2015, 2017, 2019 and 2026** before purchase.

   **Second:** validate samples against exchange records, distinguish original results from revisions/XBRL, and measure missing timestamps.

   **Third:** use authorized manual exports only if bulk delivery fails. Conditional estimates: annual all-market exports mean approximately **10–12 files**; monthly exports **120–143**; annual per-symbol exports **1,000–1,200**. Additional subject passes multiply these. Actual limits remain **UNVERIFIED**.

   **Fourth:** preserve raw evidence and historical index membership. Today’s NIFTY 100 introduces survivorship bias. The importer can also miss singular “Financial Result Updates” unless its details contain “financial results.”

5. **Missing times and download terms**

   For the primary timestamp-dependent backtest, missing dissemination means **ineligible**. A separate conservative experiment may use the next trading-session open after a **verified public-release date**, regardless of unknown board-meeting time. A meeting date or reporting-period date alone is insufficient. Never use that day’s close before an unknown release, or backfill original earnings with later restatements.

   [NSE terms, clause 9](https://www.nseindia.com/static/nse-terms-of-use) prohibit **systematic or automated collection**. [robots.txt](https://www.nseindia.com/robots.txt) broadly allows crawling, but grants no contractual permission. Even systematic manual bulk collection warrants written authorization; use licensed delivery rather than scraping.