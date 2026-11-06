# Pre-registration: monthly_momentum (long hold)

**Frozen:** 6 November 2026, before any code or real-data result for this
family. Evidence and source permissions:
[`sources/2026-11-06-codex-factors-and-news.md`](sources/2026-11-06-codex-factors-and-news.md).
Real-data trials before this family: 6 (earnings_reaction 4, weekly_loser_reversal 2),
all NO-GO. Not investment advice.

## Why this family

Price momentum has the broadest Indian evidence of the factors we can build
from price data: IIM Ahmedabad's Indian four-factor library (12-1 month
winners minus losers, 10.65% a year since 1994 as a long-short factor), and
NSE's Nifty200 Momentum 30 (launched 2020; beat its parent 2021-2025, lost to
it in 2025). It trades about once a month, so the ~0.7% round-trip cost that
sank both short-hold families matters far less. The evidence is for diversified
indices and long-short factors, not a five-stock long-only portfolio; this
test is whether it survives that translation.

## Precondition: no test on today's members

Momentum on today's NIFTY 100 is badly biased: it can buy future members
before they joined. **This family must not be run until point-in-time NIFTY
100 membership from 2014 onwards is reconstructed** (owner-downloaded index
change notices, with announcement and effective dates) and every former
member that is still listed has Kite history. Former members with no
obtainable prices (delisted or merged) are listed in the result, and if they
exceed 10% of member-months the verdict is CAN'T TELL.

## Rules (fixed)

| Component | Rule |
|---|---|
| Variants | `M12`: C(D-21)/C(D-252) - 1. `M12V`: M12 divided by the sample standard deviation of the 252 daily log returns ending D. Nothing else. |
| Universe | NIFTY 100 members effective at D's close (point-in-time), Nifty 50 index excluded; 253 consecutive valid daily bars through D. |
| Schedule | D = last NSE session of each calendar month. |
| Ranking | Score descending, ties by symbol; target = top 5. No absolute-return threshold, no regime filter. |
| Exit | Holdings not in the target sell at D+1 open. No stop, no target, no maximum hold. |
| Entry | Target names not held buy at D+2 open (after sale cash settles), in rank order; whole shares, each purchase capped at 20% of equity at that open including fees, settled cash only. Rejected entries expire until next month. Held targets are kept without resizing. |
| Costs | Zerodha delivery fees; 10 bps base slippage each leg, doubled to 20 bps at the gate; idle cash earns nothing. |

## Evaluation (fixed)

Development 2015-01-01 to 2025-11-05 (warm-up from 2014 if membership and prices
allow), four chronological folds, fresh ₹2,00,000 each, best median fold net
Sharpe. All existing gates, at least 30 completed trades per fold (otherwise
CAN'T TELL, with no manufactured exits), and a full-engine random baseline:
same rebalance dates and replacement counts, random point-in-time members,
identical execution, 1,000 runs, seed 0, beat the 95th percentile. Also
reported, not gated: buy-and-hold Nifty 50 over the same folds. The sealed
final 12 months open only if the selected variant's development median Sharpe
is positive. If development fails, the family is rejected and not tuned.
Lifetime trials after this family: 8.
