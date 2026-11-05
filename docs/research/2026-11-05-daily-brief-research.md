# Daily brief: how traders decide, and what to show each day

**Date:** 5 November 2026. **Researchers:** Claude (Reddit, YouTube, web via
Agent Reach) and Codex (six-perspective web research). Full Codex reports:
[`sources/2026-11-05-codex-daily-decisions.md`](sources/2026-11-05-codex-daily-decisions.md)
and [`sources/2026-11-05-codex-results-filings.md`](sources/2026-11-05-codex-results-filings.md).
Builds on [`2026-11-05-strategy-and-tool-research.md`](2026-11-05-strategy-and-tool-research.md).
Not investment advice.

## 1. Bottom line

1. **The brief should answer "what changes my next action?"**, not "what
   happened in the market". Open positions and scheduled exits come first,
   then today's earnings candidates, then a small context strip. Claude and
   Codex agree.
2. **Less is better.** A lab experiment (Review of Accounting Studies, 2009)
   held information quality fixed: more information made traders more
   confident and more aggressive, and less wealthy. Barber and Odean (2008)
   show individuals buy attention-grabbing stocks: a news-heavy screen
   changes what you consider before any discipline applies. Cap the brief by
   decisions; an empty news section is fine; "nothing to do today" is a
   normal outcome.
3. **Only one market item is a signal today:** the Nifty 200-day regime test
   already in the strategy. Everything else (GIFT Nifty, global cues, VIX,
   FII/DII, PCR, crude, rupee, yields) is context. Do not average unrelated
   indicators into a "market mood" score.
4. **Start logging tomorrow, test in a year.** Archive every brief input with
   the time it was first seen. That turns today's context into tomorrow's
   testable factors without look-ahead.

## 2. How traders actually decide

Common pattern across published processes (Vijay Thakkar, Sudarshan Sukhani,
Zerodha Varsity, Reddit routines): **narrow the universe → find a setup →
define where you are wrong → size → wait.** Most real work happens after the
close; the morning only checks what changed.

- Sukhani's newsletter states each decision as one of: buy tomorrow, buy above
  a trigger, hold, exit, with a closing-basis stop and holding period. Our
  alerts should use the same plain decision states.
- Varsity's process rejects candidates in sequence and accepts that sometimes
  nothing qualifies.
- Indian swing traders call our strategy's pattern an **"episodic pivot"**
  (big move on volume after news or results; e.g. interview with Ankur Patel).
- Reddit and YouTube routines: check open positions and stops, global cues,
  GIFT Nifty, results calendar, then shortlist. The most useful journaling
  advice: **record whether you followed your rules**, not just P&L.
- Practitioners' risk numbers differ (Thakkar's ~8% stop on a 10% allocation
  ≈ 0.8% of equity). Keep our pre-registered sizing instead of mixing rules.

Evidence caution: the self-reported returns in these sources are unverified;
we borrow process, not performance claims.

## 3. The daily brief (design)

Evening edition **18:30 IST** (after official data arrives), plus an
**08:45 IST changes-only** refresh. Holidays and special sessions respected.

| Section | Contents | Source | Role |
|---|---|---|---|
| Status | Strategy version, paper/live stage, data freshness, missed jobs, portfolio reconciled? | Local ledger, Kite | Decision input |
| Open positions | Per holding: qty, entry, sessions held, closing-stop level, scheduled exit date, new filing, upcoming corporate action, and one plain instruction ("exit next open", "no change") | Kite holdings, ledger, NSE filings | Decision input |
| Earnings candidates | Filing link and time, reaction-day stock vs Nifty return, regime pass/fail, rank, whole-share size, costs, stop, exit date | Kite prices, results events | Decision input (existing rules only) |
| Event exceptions | Result revisions, suspensions, corporate actions touching holdings/candidates | NSE notices | Review |
| Next 48 hours | Results due for holdings; RBI, India CPI/IIP, US Fed/CPI with IST times | Official calendars | Risk context |
| Market strip | Nifty regime; India VIX; GIFT Nifty, crude, USD/INR, US 10y (timestamped); optional FII/DII (provisional) | Kite, official sources | Context only (except regime) |
| Decision | Planned exits, eligible entries, skips with reasons, your acknowledgement | You | Action record |

Rules:
- At most three news items, each with publisher, link, publication time and
  first-seen time. An LLM may summarise **today's** retrieved items only;
  every number must map to a source line; headline-only summaries are
  labelled; it never fills in missing earnings figures.
- If holdings cannot be read, show **PORTFOLIO UNRECONCILED**, never zero.
- Results published overnight are queued, not entered at 09:20: the strategy
  needs a completed reaction session first.
- Closing-basis stops stay closing-basis; an intraday broker stop would be a
  different, untested strategy.

## 4. Pre-trade checklist

1. Is this strategy cleared for the current stage (paper or live)?
2. Are holdings, cash, prices and filings fresh and reconciled?
3. Has the full reaction session completed?
4. Do eligibility, ranking and regime rules pass?
5. Does whole-share sizing fit the risk, allocation and position limits after costs?
6. Are the exit date and closing stop recorded?
7. Is this planned, not chasing news or recovering a loss?

**Journal row:** decision time · brief/strategy version · symbol and event
link · enter/hold/exit/skip and reason · planned qty, price, stop, exit date ·
estimated costs · actual fill, time, fees · rule deviation (yes/no, what) ·
emotional state · outcome · one lesson. Log skipped candidates and no-trade
days too. Review weekly; score rule-following separately from profit.

## 5. News and data sources

| Source | Use | Caveat |
|---|---|---|
| Kite (your account) | Prices, holdings, positions | Daily login |
| NSE RSS (announcements, results, board meetings, corporate actions, insider trading) | Live event discovery | NSE's terms forbid systematic automated collection and restrict storage/reuse; confirm before building an archive on it. Manual downloads for history |
| Economic Times RSS | Headlines | Free for personal, non-commercial use with attribution |
| GDELT | Article discovery | Rolling three-month window; not publisher timestamps |
| RBI, MoSPI, BLS, Fed calendars; US Treasury yield XML | Macro calendar | Check each release's stated time; MoSPI CPI now 16:00 |
| NewsAPI | Not suitable | Free tier is 24h delayed and non-production; paid is $449/month |
| Google News / Moneycontrol RSS | Optional discovery | Terms and latency unverified; not a dependency |

## 6. Archive now, test later

For every input, keep: source URL, document version and checksum, event time,
stated publication time, first-seen time, ingestion time, revision status,
and the brief actually delivered (including any LLM output and prompt
version). Append only; never overwrite with later revised numbers (FII/DII
provisional data in particular). Re-running a future model over old news
does not recreate what was knowable then.

Candidate factors to pre-register in about a year: reaction size, abnormal
turnover, closing location in the day's range, overnight gap,
sector-relative reaction, VIX regime, announcement timing, number of
competing announcements. Flows and PCR are low priority.

## 7. What not to include

Stock tips, influencer P&L, daily profit targets, "smart money" stories
read from open interest, sentiment scores without sources, duplicate
headlines, full bulk/block/insider tables (show only rows touching holdings or
candidates), and any pressure to trade every day.
