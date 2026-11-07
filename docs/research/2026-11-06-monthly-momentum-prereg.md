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

## Amendment 1 (6 November 2026, before any data for this family was downloaded or inspected)

The point-in-time NIFTY 100 precondition is replaced. Reconstructing it needs
roughly 250+ niftyindices notices (20-30 a year since 2014: semi-annual
reviews plus ad hoc replacements), each a multi-index PDF; too error-prone to
do by hand. Replacement universe, computed only from data available at D:

| Component | Rule |
|---|---|
| Candidates | Every plain NSE equity symbol (no series suffix) in Kite's instrument list of 2026-11-05 with Kite daily history. |
| Universe at D | The 100 candidates with the highest median daily traded value (close x volume) over the 126 sessions ending D, among those with 253 consecutive valid bars through D. Ties by symbol. |
| Everything else | Unchanged (M12, M12V, monthly top 5, exits, entries, costs, evaluation). The random baseline draws from the same point-in-time universe. |

Known residual bias: companies delisted or merged before 2026-11-05 are not
in Kite's list and cannot enter the universe (for example HDFC Ltd, merged
2023; DHFL, delisted 2021). The result must name this limit. The earlier
">10% missing member-months makes CAN'T TELL" rule cannot be computed without
true membership and is dropped; the verdict states the bias instead.

**Amendment 1a (same day, still before any price download):** "plain NSE
equity symbol" means Kite instruments with segment `NSE`, instrument_type
`EQ`, no `-` in the trading symbol, excluding funds: name matching
`\bETF\b|BEES|\bINAV\b|\bNAV$|AMC\s*-|\bFUND\b|\bREIT\b|\bINVIT\b|BHARAT BOND`
(case-insensitive) or symbol ending `BEES|IETF|ETF|INAV`. On the 2026-11-05
list this keeps 2,383 companies and drops 715 funds. History requested from
2014-01-01 for the 253-session warm-up.

## Development result (7 November 2026, commits 6f8af55..1da2429)

Input: Kite adjusted daily candles 2014-01-01 to 2026-11-05 for 2,357 of the
2,383 Amendment 1a candidates (gone from Kite's list: PRIORITY, VENUSREM, VIRAT,
ATLANTAA, LEMERITE, ZEEMEDIA; conflicting daily bars: AHLADA, APOLSINHOT, BANG,
BBTCL, BEARDSELL, CLEDUCATE, EIFFL, GANESHBE, INDOWIND, KAPSTON, KMSUGAR,
PANSARI, RAJRATAN, SEJALLTD, SHANTI, SONAMLTD, TEMBO, TIL, VINEETLAB, WEWIN).

Net profit ₹ (net Sharpe) per fold, fresh ₹2,00,000 each, 20 bps slippage:

| Variant | 2015–17 | 2017–20 | 2020–23 | 2023–25 | Median Sharpe |
|---|---|---|---|---|---|
| M12 | −20,998 (−0.09) | −5,747 (0.07) | +69,728 (0.53) | +2,19,739 (1.02) | **0.30** |
| M12V | −15,969 (−0.04) | −22,467 (−0.08) | +90,764 (0.64) | +2,28,969 (1.14) | 0.30 |
| Nifty 50 buy-and-hold (context, before costs) | +45,458 | −5,378 | +1,75,994 | +84,964 | |

Selected: **M12** (median fold Sharpe 0.2985 vs M12V 0.2987 rounds equal; the
rule's tie-break picked M12). Positive, so the sealed year may be opened once.
Caution recorded before opening: the strategy trailed buy-and-hold Nifty in
three of four folds; its edge rests on 2020-25.

## Amendment 2 (7 November 2026, before the sealed year was opened)

The final data-coverage check compared the locked window against a grid of
every candidate on every session: 9.9% of those pairs are missing (illiquid
names, new listings), which would make the verdict CAN'T TELL regardless of
the strategy. For this family the check now covers only symbols that were in
the point-in-time universe at some session of the locked window, the names
the strategy could trade; the 2% threshold is unchanged. Decided from coverage
counts only; no locked-window returns were computed or viewed.
