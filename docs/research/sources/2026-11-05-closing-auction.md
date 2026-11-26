**Yes—CAS explains your RELIANCE observation.** Findings checked **5 November 2026**.

1. **Go-live and scope:** CAS started **3 August 2026** for **cash equities with derivatives contracts**, not all stocks. Their continuous session ends at **15:15 IST**; non-CAS equities continue until **15:30**. Sources: [SEBI circular, 16 January 2026](https://www.sebi.gov.in/sebi_data/attachdocs/jan-2026/1768576287344.pdf), [NSE timings, updated 12 August 2026](https://www.nseindia.com/static/products-services/closing-auction-session).

   | Phase | IST |
   |---|---|
   | Reference-price calculation / transition | 15:15–15:20 |
   | Market and limit order entry/modification/cancellation | 15:20–15:25 |
   | Limit orders only; market orders frozen | 15:25–random closure between 15:28 and 15:30 |
   | Matching and confirmation | Immediately after random closure; nominal window 15:30–15:35 |
   | Transition/buffer | 15:35–15:50 |
   | Post-close trading at closing price | 15:50–16:00 |

2. **Trades versus candles:** Actual auction trades execute during matching. Before matching, indicative prices/quantities are **not executed trades**. Auction executions can therefore contribute to daily OHLCV without producing continuous-session intraday candles.

   Kite staff explicitly stated on **14 August 2026** that, from August 3, CAS-stock historical candles stop at 15:15. Thus the last start-labelled five-minute candle is **15:10**. Kite’s UI can show an additional auction candle; it differs from historical API output. [Kite CAS thread](https://kite.trade/forum/discussion/comment/52786/). On **12 August 2026**, support also confirmed daily candles use exchange bhavcopy, whereas intraday candles use live feeds—so daily volume need not equal summed intraday volume. [Support explanation](https://kite.trade/forum/discussion/16171/historical-data-api-missing-minute-candles-after-15-14).

3. **Older history:** **Yes, expect mixed session shapes.** A **February 2019** Kite staff reply reproduces RELIANCE’s **31 January 2018, 15:25** five-minute candle. The thread also contains 15:15 and 15:20 bars. [Historical evidence](https://kite.trade/forum/discussion/5536/last-minute-candle-of-the-day-5mins-data). Completeness of every pre-change day is **UNVERIFIED**.

4. **Backtester recommendation:**

   - Build expected grids by **date + instrument + historical CAS eligibility + vendor**. Ordinary full sessions: **75 bars before CAS; 72 for eligible stocks afterward; 75 for non-CAS equities**. Keep indices on their own feed schedule; your NIFTY observation does not establish every index/day (**UNVERIFIED**).
   - Treat those three absent RELIANCE slots as **outside its continuous session**, not missing data. Do not forward-fill them into executable bars.
   - “Closed by 15:15” requires execution **before continuous trading ends**. Never wait for a 15:15 candle or use the daily/auction close. A scheduled fill using the **15:10 candle’s close** is a modelling approximation; a live implementation needs an earlier execution margin. Do not use that completed candle to generate a signal and retroactively fill its close.
   - For a common strategy window, use bars covering **[09:15, 15:15)** across symbols, while retaining full vendor history separately.

**Another dated change matters:** SEBI’s **15 October 2026** circular schedules CAS to move to **15:30–15:40 from 7 December 2026**. Version the calendar again; future Kite candle behaviour remains **UNVERIFIED**. [SEBI revision](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792079571420.pdf).