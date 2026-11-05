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
- The baseline matches actual traded symbols/quantities/realized hold durations
  and next-open entries following any timed-results event day. Independent
  sampling still allows overlap and unaffordable portfolios and does not rerun
  ATR stops or equity sizing. Replacing that vectorized sampler with a full
  portfolio simulation is beyond the cheap timing extension; the new
  `random_portfolio: CAN'T TELL` gate prevents false pre-registration compliance.
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
