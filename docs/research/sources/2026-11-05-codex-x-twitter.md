**I found useful research ideas, but no sampled X post establishes a repeatable NSE retail strategy profitable after all costs.** Several report trading profits; their live execution, complete account history and net returns remain **UNVERIFIED**.

Search cutoff: **5 November 2026**. Direct X access was patchy; links below identify mirrors and first-party fallbacks. Follower counts were generally unavailable or stale. No files were edited.

On **strategy claims**:

| Who / date | Brief quote and claim | Evidence assessment |
|---|---|---|
| **@MashraniVivek**, TechnoFunda founder; profile describes him as a SEBI RA — **8 Feb 2025** | PEAD: prices continue moving “for weeks or even months after the earnings.” [ThreadReader](https://threadreaderapp.com/user/MashraniVivek) | Confirmed educational explanation with commercial context. No NSE trade ledger, cost model or live PEAD returns shown in the accessible excerpt. |
| **@JayneshKasliwal**, intraday algo trader/educator — **6 Nov 2025** | Swing selection: “stocks that gained 50%+” over 3–4 months. [ThreadReader](https://threadreaderapp.com/user/JayneshKasliwal) | Momentum screening hypothesis. Promotional language; no authenticated performance evidence. |
| **@AdityaTodmal**, options educator — **26 Jan 2025** | Attributes a “return of 94% this FY” to **@VVVStockAnalyst**, reportedly growing ₹1.94 crore to ₹3.74 crore. [ThreadReader](https://threadreaderapp.com/user/AdityaTodmal) | Second-hand reported trading results, not a backtest. **UNVERIFIED** capital flows, costs, drawdowns and live records; promotional success narrative. |
| **@JayneshKasliwal — 5 Nov 2025** | Options selling: “Generated 24k profit on 5 lakh capital” in one month—4.8% arithmetically. [ThreadReader](https://threadreaderapp.com/user/JayneshKasliwal) | Post confirmed; actual live profitability **UNVERIFIED**. One month and an indicator explanation do not establish net expectancy. |
| **@SystemTraderIN — 16 Sep 2026**, date stated in indexed post | “P&L : ₹50606”; ₹2 crore capital, September ROI 9.3%, with **#VerifiedBySensibull**. [Indexed mirror](https://www.sotwe.com/SystemTraderIN?lang=id) | **UNVERIFIED:** mirror would not open. Explicit live-results marketing lead; the hashtag itself verifies nothing. |
| **@nooreshtech — 21 Feb 2025**; **@itsTarH — 24 Feb 2025** | Nooresh: promoter buying—“What to Look For & What to Avoid?” Tar reports ₹790 crore Jindal Steel promoter buying, promoting TheWrap. [Nooresh mirror](https://threadreaderapp.com/user/nooreshtech), [Tar mirror](https://threadreaderapp.com/user/itsTarH) | Useful event-discovery material; neither accessible post demonstrates profitable post-disclosure execution. Underlying purchase figures were not independently checked. |

For **ORB/intraday and bulk/block-deal following**, I found no qualifying, confirmed 2025–26 X record demonstrating after-cost live profitability. A revealing **non-X fallback**, Pranay/DailyBulls, **11 November 2025**, advertises **71.4% ORB win rate**, but explicitly says “All testing assumed zero costs.” It is a 42-trade backtest, not live evidence. [Original](https://dailybulls.in/orb-intraday-trading-strategy-backtest/)

On **Zerodha, authentication and regulation**:

- **@Nithin0dha — 6 May 2025:** announced data APIs at “Rs 500 per month,” reproduced by Zerodha’s forum alongside the ≤10-orders/second individual-algo threshold and static-IP requirement. This is broker product/regulatory communication, not return evidence. [X original](https://x.com/Nithin0dha/status/1919687724027551901), [confirmed reproduction](https://tradingqna.com/t/a-comprehensive-overview-of-nse-s-new-retail-algo-trading-framework/181989). Current Zerodha support specifies static IP for **order placement from 1 April 2026**; WebSocket data and other listed read APIs remain accessible from any IP. [Support](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip)

- **Kite forum, salim_chisty — August 2025**; exact day unavailable: “We don't recommend automating login,” responding to a broken Playwright 2FA workflow. [Post](https://kite.trade/forum/discussion/15380/automating-login-process). Current documentation says access tokens expire at **6 AM next day**; long-standing read refresh tokens are restricted to approved platforms. Browser login → request token → access token remains the documented flow. [Documentation, checked 5 Nov 2026](https://kite.trade/docs/connect/v3/user/). I found no confirmed relevant Kailash Nadh/Rainmatter X post endorsing TOTP login automation.

- **@Nithin0dha — 28 July and 5 August 2026:** explained CAS launching **3 August**, then wrote “CAS itself is not a bad idea,” attributing dislocations to shallow liquidity, shorting constraints and costs. [July archive](https://nithinkamath.me/blog/introduction-of-the-closing-auction-session-cas-from-august-3/), [August archive](https://nithinkamath.me/blog/thoughts-on-cas-and-what-we-can-do-better/). **Date trap:** October reporting describes revised **3:30–3:40 PM CAS from 7 December 2026**, still future at this cutoff. The circular’s existence/date opened; its PDF did not—full primary-text verification remains **UNVERIFIED**. [17 Oct explanation](https://www.groundamentals.com/insights/77-sebi-changes-expiry-day-settlement-under-closing-auction)

For **Upstox, Dhan and FYERS**, relevant dated X originals remained **UNVERIFIED**; these are confirmed first-party fallbacks:

- **Upstox — 20 March 2026 launch; 6 June expansion:** “1-year validity,” read-only Analytics Token. Market data/history/WebSocket access needs no static IP; account-specific GET access requires one. It cannot place orders. [Launch/date index](https://upstox.com/developer/api-documentation/announcements/), [June notice](https://upstox.com/developer/api-documentation/announcements/analytics-token-static-ip/)
- **Dhan support, Shubham_Singh — 22 September 2025:** “access token validity has been changed to 24 hours.” [Post](https://madefortrade.in/t/why-option-of-api-validity-of-24hrs-only/56194). Current docs distinguish a **12-month API key/secret** from the access token, document TOTP token generation, and distinguish free trading APIs from charged data APIs. [Docs, checked 5 Nov 2026](https://dhanhq.co/docs/v2/authentication/)
- **FYERS — 10 March 2026**, effective **1 April:** “Continuous refresh-token sessions will no longer be supported”; daily 2FA required. This supersedes relying on older refresh-token claims. [Notice](https://fyers.in/notice-board/new-sebi-framework-for-retail-algo-trading-from-april-01-2026)

On **SEBI evidence**, the strongest material was official publications rather than accessible X originals:

- **4 February 2025:** framework titled “Safer participation of retail investors in Algorithmic trading.” [Circular](https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html)
- **20 August 2026:** FY26 net individual derivatives losses **₹91,685 crore**, versus approximately **₹1.12 lakh crore FY25**; **87.7%** lost in FY26. Crucially, predominantly option sellers were the only strategy group with **“positive median returns”** on capital employed—but represented only around 2% of traders. This is observational broker-data evidence, not validation of a retail selling recipe. [Opened SEBI release](https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787236407005.pdf)
- The familiar **“7 out of 10” intraday-loss** finding is a **24 July 2024** release, not a FY25/FY26 update. I found no newer cash-intraday study in SEBI’s research listing. [Release](https://www.sebi.gov.in/media-and-notifications/press-releases/jul-2024/sebi-study-finds-that-7-out-of-10-individual-intraday-traders-in-equity-cash-segment-make-losses_84948.html)

**Five useful takeaways for your personal research/paper-alert tool:**

1. Use PEAD, momentum and disclosed buying as testable hypotheses; start with timestamped alerts.
2. Preserve filing publication time and first executable price to prevent hindsight leakage.
3. Record brokerage, statutory charges, spreads, slippage and data/subscription costs.
4. Evaluate Upstox’s read-only token for unattended data ingestion; keep authentication provider-specific.
5. Version session calendars, CAS eligibility, closing-price definitions and regulatory effective dates.

**Red flags/common failures:** cropped P&L, missing capital flows, selected winning months, “verified” hashtags without accessible records, zero-cost backtests, and confusing long-lived API keys with trading sessions. Operational failures include broken browser/TOTP automation and expired tokens. SEBI itself warned on **17 August 2026** against trusting social-media “live trading strategies.” [Warning](https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1786977152255.pdf)