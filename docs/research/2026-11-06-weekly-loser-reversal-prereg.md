# Pre-registration: weekly_loser_reversal (1-10 day swing)

**Frozen:** 6 November 2026, before any code or any real-data result for this
family. Proposal and evidence: [`sources/2026-11-06-codex-swing-proposal.md`](sources/2026-11-06-codex-swing-proposal.md).
Trial history at freeze: only `earnings_reaction` (4 trials) has touched real
data; `short_reversal` has never been run on it. Not investment advice.

## Hypothesis

Large, liquid NSE stocks that were the worst performers over the past week
partly rebound over the next one to two weeks (prior-week reversal; de Groot,
Huij and Zhou 2011, large-cap US/European stocks). This is an adaptation, not
a replication: long-only, next-open entry, Indian costs.

## Rules (fixed)

| Component | Rule |
|---|---|
| Variants | `h5`, `h10` (holding cap 5 or 10 sessions). Nothing else. |
| Universe | Frozen NIFTY 100 list (`deploy/nifty100_2026-11-05.txt`), Nifty 50 index excluded. Needs 21 consecutive daily bars through D, positive OHLC and volume, ATR20 > 0. |
| Features at D close | r5 = C_D / C_{D-5} - 1. ATR20 = mean of 20 true ranges through D. |
| Signal | Rank eligible stocks by r5 ascending (ties by symbol). Among the first floor(0.20 x N_D), buy only those with r5 < 0. |
| Priority | Most negative r5 first. All qualifying orders submitted; portfolio capacity rejects the rest. |
| Entry | D+1 open, adverse slippage. Skip symbols already held; no pyramiding, no queued orders. |
| Sizing | Existing engine: whole shares, max 5 positions, 20% cap, 0.25% equity risk per 2xATR, settled cash, Zerodha delivery fees. |
| Stop | Entry minus 2 x ATR20_D, frozen. A close strictly below it sells at the next open. |
| Exit | Stop or holding cap, whichever first. Entry session = session 1; exit at the open after session H closes (engine holding_sessions = 4 / 9). No target, no trailing stop. |
| Regime | None. |
| Slippage | 10 bps base, doubled to 20 bps at the gate; single grid point. |

## Evaluation (fixed)

Development 2015-01-01 to 2025-11-05, four chronological folds, fresh
₹2,00,000 each, selection by best median fold net Sharpe. GO requires all
existing gates, including a full-portfolio random baseline: same signal dates
and counts, random history-eligible stocks (no loser filter), identical
execution, 1,000 runs, seed 0, beat the 95th percentile. The sealed final 12
months are opened only if the selected variant's development median Sharpe is
positive. If development fails, the family is rejected and not tuned.

Known limits: survivorship bias (today's members), no dividends, daily bars
cannot see intraday liquidity or circuit limits.

## Result (6 November 2026, commit 7fd8a11)

Development folds (fresh ₹2,00,000 each, 20 bps slippage): net profit ₹ (net Sharpe).

| Variant | Fold 1 (2015–17) | Fold 2 (2017–20) | Fold 3 (2020–23) | Fold 4 (2023–25) | Median Sharpe |
|---|---|---|---|---|---|
| h5 | −16,052 (−0.83) | −38,209 (−1.97) | −14,486 (−0.69) | −9,798 (−0.49) | −0.76 |
| h10 | −4,860 (−0.25) | −21,152 (−1.11) | +4,527 (0.25) | +3,019 (0.18) | −0.04 |

**NO-GO.** Neither median is positive; the holdout stays sealed and the family
is rejected as pre-registered. Not to be tuned (e.g. longer holds, regime
filters) on this evidence. Lifetime real-data trials: 6.
