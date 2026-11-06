# Earnings reaction implementation handoff

Implemented the four pre-registered daily variants with `--strategy
earnings_reaction --index-symbol "NSE:NIFTY 50"`. Existing families retain
their search grids and sizing. No staging, commit, push, deployment or live
data access was performed. The pre-existing untracked
`deploy/nifty100_2026-11-05.txt` was left untouched.
An unrelated concurrent edit to `src/autopsy/data/kite.py` appeared during the
final status check; it was not authored or changed by this task.

Changed files:

- `src/autopsy/strategies/earnings_reaction.py`: event/session eligibility,
  reaction, SMA200, simple ATR20, index context and ranked managed orders.
- `src/autopsy/strategies/__init__.py`: four-value variant registry; include
  engine implementation in the registry hash because it now owns stop/hold rules.
- `src/autopsy/engine.py`: optional order priority, risk sizing and managed
  close-triggered exits. The existing five-position cap and T+1 cash rules apply.
- `src/autopsy/cli.py`: strategy filtering, index exclusion, clear refusals.
- `src/autopsy/research/walkforward.py` and `lock.py`: fixed family slippage,
  preserved index context and hashes covering index identity/history.
- `src/autopsy/stats.py` and `verdict.py`: optional season timing restriction;
  explicitly block GO on the incomplete portfolio baseline.
- `tests/test_earnings_reaction.py`: invented-data behavioral and CLI tests.
  `test_events.py` and `test_strategies.py`: update registry cardinality assertions.
- `README.md` and this handoff: execution conventions, deviations and gaps.

Execution and sizing: completed D produces the order; entry is next available
daily open with adverse slippage. Base slippage is fixed at 10 bps, doubled to
20 bps per leg in research/holdout, avoiding an accidental 12-trial search.
Whole-share size is the floor of the smaller of 20% opening equity divided
by the slipped fill and 0.25% opening equity divided by twice simple ATR20.
Fees and settled cash can further reduce quantity. Equity is marked after
exits, before the batch of entries, without current-bar closes. Stops freeze
at actual slipped entry minus twice D's ATR; only a strictly lower completed
close triggers a next-open exit. Rejected entries create no holding state.

Deviations and remaining gaps:

- Daily opens approximate the research document's 09:20 fills, as requested.
  No intraday liquidity or stop-touch simulation. Missing bars can postpone
  fills to the next observed bar under the existing engine convention.
- Holding age matches `_holding_signals`: entry session is zero, age N emits
  an exit for the next open, so entry-to-exit is N+1 opening intervals.
- Date-only sessions assume 09:15 for dissemination eligibility; explicit
  timed schedules retain their opens. Missing entire sessions/special-session
  clocks require an independent calendar to resolve.
- Historical index context warms SMA200, but the sealed stock input has no
  earlier ATR warm-up: its first 20 sessions are ineligible. Development folds
  use preceding development history normally.
- Resolved 2026-11-06: the earnings family now runs 1,000 deterministic full
  portfolios through the same managed-entry engine. Signal-day order counts
  match the strategy (submitted orders, including rejected entries), on the
  eligible results calendar. Symbols are uniform without replacement among
  that day's rows with completed positive finite ATR20; index excluded, random
  priority, own-symbol risk distance, selected N-session hold. Existing held
  symbols can be drawn; ordinary engine rejection applies. Order opportunities
  match, but actual fills/exposure can differ with cash, stops and capacity.
  The statistic is final marked equity minus initial cash, including unclosed
  holdings, exactly as in the verdict. Strategy profit must strictly exceed
  p95. Successful baseline execution lifts the portfolio gate; failures and
  all families still using the legacy sampler retain CAN'T TELL.
- Full-baseline replay reconstructs the locked strategy orders from its locked
  input and parameters and refuses mismatched fills/equity. The existing
  walk-forward selection and ATR warm-up convention are unchanged. No real
  strategy edge has been evaluated by this implementation.
- Point-in-time NIFTY 100 membership and dividend cash flows remain absent.
  The imported list is a fixed universe. Existing fold selection still chooses
  among the four variants; the primary is identified but is not forced to win.
- Adding the family/engine sources changes registry hashes; old locks must
  not be treated as evidence for this implementation.

Validation: `.venv/bin/python -m pytest -q` completed with **508 passed,
3 skipped, 3 warnings in 108.96 seconds**. Forty new test cases were added;
three existing real-socket login tests skipped under the sandbox. The warnings
come from the retained original Oracle case. `git diff --check` is clean.
After the concurrent Kite edit appeared, `pytest -q tests/test_kite.py` also
passed all 84 tests in 0.94 seconds.
All new tests use invented data and no network. Tests cover math, strict dissemination,
truncation, actual-fill stops, hold counting, risk sizing, ranking/capacity,
four trials, CLI filtering/exclusion, refusals, snapshots/hashes and baseline
season timing.

Shared-brain handoff: read the vault index, ACTIVE_STATE and binding rules.
The sandbox only permits writes in this workspace and temporary directories,
so `~/SecondBrain` and its ACTIVE_STATE could not be updated. This file retains
the decisions and handoff locally for the owner to reconcile into the vault.

## Full-portfolio follow-up, 2026-11-06

The engine now separates reusable validated market/session inputs from mutable
execution state. Public backtests and random portfolios call the same execution
loop; only the symbol choices and priorities change. Cash, holdings, settlement,
pending exits, costs, stops and mark-to-market all restart per run. ATR features
and draw pools are computed once. No multiprocessing or approximate cost model.

Offline benchmark: `.venv/bin/python tests/benchmark_random_portfolio.py`,
100 invented symbols × 2,700 daily sessions, 4,000 strategy orders / 854 fills,
200,000 starting cash, `h10_regime`, 20 bps slippage per leg, Zerodha rates.
Measured with `perf_counter` on this development machine:

| Measurement | Seconds |
| --- | ---: |
| Original engine, one run | 1.160 |
| Original engine × 1,000 (projection only) | 1,160.5 |
| Refactored public engine, including preparation/record validation | 1.297 |
| Baseline preparation, features, pools and exact strategy replay | 12.646 |
| One prepared random draw + engine run | 0.087 |
| 1,000 prepared random draw + engine runs (measured sequentially) | 105.871 |
| Baseline preparation + measured 1,000 runs | 118.517 |

One process throughout, below the four-process limit and ten-minute budget.
The test workload and edge fixtures are confined to `tests/`; no network or
real-market data access. Timings vary with event density and hardware.

Follow-up validation: `.venv/bin/python -m pytest -q` finished with **529 passed,
3 skipped, 3 existing Oracle warnings in 80.26 seconds**. Eighteen new cases
cover exact own-choice replay across all four variants, missing bars, stops,
share actions, deterministic seeds, uniform candidate pools and random order,
submitted versus filled counts, index exclusion, event-free sessions, own ATR,
open-position PnL, cash/fees/T+1, rejected metadata/replays, planted edge versus
no edge, and the full-baseline-only verdict gate. Legacy-family gate tests
were updated while retaining their independent checks of the other criteria.
`git diff --check` is clean. The three skips are sandbox socket tests.

Decisions for the shared-brain handoff: match submitted order counts rather than
filled trades, never filter random candidates on future bars or returns, retain
held symbols in the pool, compare open-position-inclusive account PnL, and lift
the portfolio gate only after a successful full-engine baseline. The vault and
ACTIVE_STATE remain outside writable roots, so this repo handoff records the
state for later reconciliation. No staging, commit or push performed.
