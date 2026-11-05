# Strategy and tool research: what to build next

**Date:** 5 November 2026. **Researchers:** Claude (web, Reddit, YouTube, GitHub
via Agent Reach) and Codex (four independent web-search runs, including X).
Full Codex reports are in [`sources/`](sources/). Nothing here is investment
advice; no strategy has reached GO.

## 1. Bottom line

1. **Build one strategy first: long-only earnings-reaction continuation,
   held for days, not minutes.** Claude and Codex reached this independently.
   Intraday ORB stays as a benchmark, not the main bet.
2. **Day trading is the hardest place to make money.** SEBI's July 2024 study:
   71% of individual cash-intraday traders lost money in FY23, 80% of those
   with more than 500 trades a year. Losers' costs equalled 57% of their
   trading losses. For F&O, 87.7% of individuals lost money in FY26
   (₹91,685 crore). Our own cost table says an intraday round trip costs
   about 0.11% before slippage, about 0.3% with the final gate's doubled
   slippage, every single trade.
3. **Honest odds: roughly 5–20% that the strategy passes every gate** (two
   separate Codex estimates; Claude agrees with the range). A NO-GO is the
   most likely result and is still useful: it stops real money going in.
4. **Daily login is solved without automating Kite.** Use Upstox's free,
   read-only **Analytics Token (valid one year)** for unattended daily data and
   live quotes. Keep Kite for occasional bulk history downloads, with one
   manual login each time. Zerodha staff (Aug 2026): "a user is required to
   log in manually at least once a day", and they do not recommend automating
   it. We will not store your password or TOTP secret.
5. **No orders from the tool.** Alerts plus you placing the order yourself in
   the normal Kite app keeps this workflow outside the API-algo rules.
   A button that calls the order API would still count as API trading.

## 2. Evidence summary

| Idea | Evidence for India | Verdict for us |
|---|---|---|
| Post-earnings drift (PEAD) | Academic studies find drift over ~64 days on NSE stocks; Ceta Research's 25-year, 14-exchange study (May 2026, corrected Aug 2026) finds Indian earnings beats drift **+2.93%**, while US beats do not drift | **Build first** |
| Momentum / 52-week high | Moderate evidence at monthly horizons; a 2019 study finds a long-only NIFTY 100 top-decile portfolio beat the index after turnover | Second candidate |
| Short-term reversal | Strongest in illiquid stocks, where execution is worst | Skip |
| Opening-range breakout | Practitioner tests conflict; one vendor's Nifty-futures ORB loses before costs; a popular blog's "71% win rate" assumed zero costs | Benchmark only |
| Gap fade/continue | No reliable modern after-cost evidence found | Benchmark only |
| Bulk/block deals | Most of the move happens on the deal day; deals are published after the close | Weak |
| Promoter buying (SAST) | Longer-horizon effects reported (2026 paper); 1–20 day after-cost edge unverified | Later, as a filter |
| FII/DII flows | Returns drive flows as much as flows drive returns; data is aggregate and revised | Skip |
| Delivery % | Small samples; no tradable rule shown | Skip for now |
| India VIX / Nifty trend | Useful as a risk filter, not a signal | Use as regime filter |
| News sentiment (text) | No complete, timestamped historical news archive; an AI labelling old headlines already knows what happened next, which leaks the future into the backtest | **Do not use historically** |
| Options selling | SEBI FY26: option sellers were the only group with positive median returns, but only ~2% of traders; tail losses can be unlimited | Out of scope |

## 3. The strategy to research (pre-registered)

**Event.** A company's quarterly results, from NSE announcement exports with
the exchange **dissemination time**. Missing time means the event is skipped.

**Reaction (the "news" factor, measured by price).** Let D be the first full
session after the results became public. Qualify if, on D, the stock closed up
and beat the Nifty 50 that day. This is a proxy for an earnings surprise,
because we have no point-in-time analyst consensus.

**Regime (the "market" factor).** Nifty 50 close on D above its 200-day
average. Usable only from the next session.

**Entry.** Next session at 09:20 at a conservative price with slippage. Rank
same-day candidates by excess return over Nifty.

**Exit.** After N trading sessions at 09:20, or the next session after a daily
close below entry − 2 × ATR(20). Morning exits avoid the closing auction.

**Sizing.** Whole shares, no leverage, at most five positions, each the
smaller of 20% of equity and 0.25% equity risk ÷ (2 × ATR).

**Universe.** Point-in-time NIFTY 100 members (liquid; no closing-auction
surprises at entry/exit times).

**Pre-registered variants (four trials, nothing else tuned):**

| # | Hold N | Regime filter |
|---|---|---|
| 1 | 10 sessions | on (primary) |
| 2 | 5 sessions | on |
| 3 | 20 sessions | on |
| 4 | 10 sessions | off (ablation) |

Every existing gate stays: independent ledger, look-ahead check, doubled
slippage, sealed final year, at least 30 trades, bootstrap lower bound above
zero, and beating 95% of 1,000 random-entry runs. Random entries must be
matched on capital, universe and earnings-season timing, because results
cluster.

**Costs to beat.** Delivery round trip from our Zerodha rate table:
0.38% at ₹10,000 per position, 0.30% at ₹20,000, before slippage. With 10 bps
slippage each way, doubled at the gate, a ₹10,000 position needs about **0.78%**
just to break even. Small positions are expensive: do not test with less than
the capital you would really use.

**Kill criteria.** Sealed-year failure, results that depend on today's index
members or on timestamps we do not have, profit that disappears at doubled
slippage, or failing the random-entry test. Do not re-tune against the sealed
year. Fewer than 30 trades is CAN'T TELL, not a pass.

### Where Claude and Codex differed

- **Holding period:** Codex's proposal said 10 days, its deep report 5 days,
  and the literature 64 days. Resolved by testing 5, 10 and 20 as fixed variants.
- **Surprise measure:** Codex's deep report suggested year-on-year EPS growth
  from the filing. That needs parsing results documents point-in-time, so it
  is a phase-2 refinement; the price reaction is available now.
- **Extra factors:** Claude also considered a volume-surge confirmation and
  sector relative strength. Both were dropped for now: each adds trials and
  makes overfitting more likely.

## 4. What the tool still needs to be useful

**Data**
- Upstox Analytics Token (unattended daily candles and live quotes). Blocked
  until the Upstox account clears KYC.
- Kite history back to ~2015 for research (built; one manual login per bulk
  download).
- Several years of NSE results announcements with dissemination times. NSE's
  site allows manual CSV downloads; collecting multiple years is the biggest
  remaining manual job, and needs a plan before building.
- Historical NIFTY 100 membership, so the backtest does not use only today's
  survivors.
- Dated session calendar: the closing auction since 3 Aug 2026, moving to
  15:30–15:40 from 7 Dec 2026.

**Engine and checks**
- A runner for exactly the four pre-registered variants (the CLI currently
  searches wider grids).
- Earnings-season-matched, capital-constrained random baseline.
- Configurable stops and sizing; dividend cash handling for multi-day holds.

**Daily use**
- Evening job: pull the day's results and candles, score candidates, and send
  a Mac/Telegram alert with the filing link, reason, size, stop and costs.
- Paper ledger with your actual fills logged, and an evening reconciliation.
- Stale-data and missed-job alarms; secrets in the macOS Keychain.

**Risk rules for any later real money**
- Only after GO, then at least 8 weeks (preferably 3 months) of paper alerts.
- Ring-fenced amount you can afford to lose (Codex example: ₹25,000), no
  leverage, no top-ups. Stop at a 5% drawdown of that amount, any data or
  execution integrity failure, or slippage persistently above the tested
  budget.
- A few weeks of real trades tests execution, not whether the edge is real.

**Tax.** Intraday is speculative business income; delivery trades are usually
short-term capital gains at 20% (frequent trading can be business income).
Keep exports for your tax filer.

## 5. Daily login: the plan

| Need | Source | Login |
|---|---|---|
| Daily candles, live quotes, paper alerts | Upstox Analytics Token | None for a year (read-only, free) |
| Deep history (2015 onward) | Kite Connect, ₹500/month | One manual login per bulk download |
| Placing real orders | Kite or Upstox apps, by you | Your normal login |

If Upstox KYC stays blocked, the fallback is a paid data vendor with machine
credentials (TrueData or Global Datafeeds; quotes needed). Kite login
automation with a stored password and TOTP is rejected: it goes against
Zerodha's stated rule and puts your account at risk.

**Decision (owner, 5 Nov 2026): Zerodha only.** One manual Kite login per
day, made as short as possible:

- The strategy uses daily bars, so one run per day is enough. Any login
  between the 15:30 close and 09:15 next day covers that day's entries (Kite
  tokens expire at 06:00).
- After the close, a Mac/Telegram reminder links to the Kite login page. The
  redirect URL points at a small local listener (for example
  `http://127.0.0.1:8742/kite`), which captures the request token and creates
  the session automatically. The owner only types the password (or lets the
  browser fill it) and TOTP.
- A missed day is backfilled at the next login; only that day's new entry
  signals are lost, and the alert says so.

## 6. What social media added

- **Reddit (r/IndiaAlgoTrading and others):** login automation is the most
  common pain point. Users script TOTP logins anyway; scripts break, and
  brokers moved to 24-hour tokens after April 2026. Strategy posts are mostly
  backtests. The most useful posts were cautionary: one found that the
  backtested edge in India's most-traded intraday strategy came mostly from
  expiry days, and the every-day version lost ₹12,054 in two months of paper
  trading. Another found that costs ate 60k of a 94k gross profit.
- **YouTube:** Tradetron's honest-profitability explainer (SEBI data and cost
  arithmetic) and Ceta Research's earnings-drift study were the useful ones;
  most videos sell courses or "passive income".
- **X (via Codex):** no post proved a repeatable after-cost NSE strategy.
  Useful confirmations: Nithin Kamath on the ₹500 data API and the closing
  auction, Upstox's one-year Analytics Token launch (20 Mar 2026), FYERS
  ending refresh-token sessions (1 Apr 2026), Dhan tokens limited to 24 hours.
  SEBI warned on 17 Aug 2026 against trusting social-media "live strategies".
- **Red flags seen repeatedly:** cropped P&L screenshots, zero-cost
  backtests, six-month tests, "verified" hashtags without records, and
  courses sold alongside results.

## 7. Key sources

- SEBI intraday study, Jul 2024: https://www.sebi.gov.in/sebi_data/attachdocs/jul-2024/1721818140715.pdf
- SEBI F&O study FY26, Aug 2026: https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787236407005.pdf
- SEBI retail algo framework, Feb 2025: https://www.sebi.gov.in/sebi_data/attachdocs/feb-2025/1738665456458.pdf
- Zerodha staff on daily manual login, Aug 2026: https://kite.trade/forum/discussion/16212/batch-automating-kite-login
- Upstox Analytics Token: https://upstox.com/developer/api-documentation/analytics-token
- Indian PEAD study (64-day drift): https://file.scirp.org/Html/20-1501629_88060.htm
- Ceta Research global PEAD comparison: https://blog.tradingstudio.finance/pead-global-comparison
- Long-only momentum in India: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3510433
- NSE closing auction: https://www.nseindia.com/static/products-services/closing-auction-session
- Reddit, login automation: https://www.reddit.com/r/IndiaAlgoTrading/comments/1vh3obr/
- Reddit, 800 YouTube strategies backtested: https://www.reddit.com/r/IndiaAlgoTrading/comments/1wfc7nr/
- Tradetron, is algo trading profitable in India: https://www.youtube.com/watch?v=lB5itupsHak

Full source lists: [`sources/`](sources/).
