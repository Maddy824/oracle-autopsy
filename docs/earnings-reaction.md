# Pre-registered earnings reaction (daily swing)

```sh
autopsy research run --mode swing --strategy earnings_reaction --index-symbol "NSE:NIFTY 50"
```

Import daily equity and Nifty candles and an NSE announcement ledger first.
`--strategy` filters the registered families; omitting it retains the full
mode search. `earnings_reaction` has exactly four parameter values:
`h10_regime` (primary), `h5_regime`, `h20_regime`, `h10_noregime`. Each is one
trial at fixed 10 bps base slippage, executed at 20 bps each way in development
and the holdout. Started/completed journal rows represent one trial, not two;
unavailable data also records exactly four rejected trials. The existing
development selection rule chooses among them; “primary” identifies the
pre-registered hypothesis, not a guaranteed selection. Other families keep
their original slippage grids.

Only `results` events with exchange dissemination times qualify (`Financial
Results` maps to this kind). Bare NSE export symbols also match their
`NSE:`-prefixed Kite symbols. No earnings-change annotation is required.
D is the first scheduled session whose open is **strictly after** the
dissemination time, with no extra minute delay. Date-only daily rows use
09:15 IST for this comparison; timed schedules preserve their opens. The
observed schedule cannot identify a missing session across every symbol, or
the true opening clock of a date-only special session.

After the completed D bar, require a positive stock close-to-close return
and strictly positive excess return over Nifty. Regime variants also require
Nifty's D close strictly above its trailing 200-session mean including D.
ATR20 is the simple mean of true ranges through D, each using the prior
close; insufficient history is ineligible. These daily features include D
without the older swing families' extra one-session feature lag. Signals
label D and execute at the next available symbol bar's **open**, multiplied
by `1 + slippage_bps/10000`; exits use `1 - slippage_bps/10000`. Daily bars
cannot reproduce the document's 09:20 execution, so next-open execution is
the explicit daily approximation. No close fills or intraday stop touches
are inferred.

The engine ranks simultaneous entries by excess return descending, then
symbol, and allows at most five positions. Whole-share quantity is
`floor(min(0.20 * equity / slipped_entry_price, 0.0025 * equity / (2 * ATR20)))`,
further reduced if notional plus fees exceeds settled cash. Equity is marked
at available opens after exits and before that batch of entries; no current
close enters sizing. Delivery proceeds remain unavailable until the next
observed day. Unaffordable/capacity-rejected orders expire. Stops use the
actual slipped fill minus the frozen `2 * ATR20`; the first completed close
strictly below that level schedules a next-open exit. Share actions rescale
the stop. Holding age follows `_holding_signals`: entry session is age zero,
the age-N close schedules an exit at the following open (N+1 session-open
intervals after entry). Existing strategies retain their fixed sizing.

The index is removed from trading rows and expected trading slots, including
when also designated as the benchmark. Its identity and serialized close
history are preserved in snapshots and lock hashes. Features restrict index
context to their current prefix; earlier index history warms the holdout's
SMA200. Equity ATR history follows the existing locked-only stock input, so
the first 20 stock sessions in the holdout cannot qualify. Missing index
prices or absence of timed results for the trading universe produces a setup
error or CAN'T TELL, not a usable candidate.

The family's random comparison runs **1,000 full portfolios**, deterministically
seeded with 0, through the same engine as the strategy. On each eligible results
event session, it submits the same number of entry orders as the strategy,
including orders the engine may reject. It draws symbols uniformly without
replacement from that session's trading rows with positive, finite completed
ATR20, excludes the index, and randomizes priority. The drawn symbols need not
have results events or positive reactions themselves. Sessions with no strategy
orders produce no random orders. Thus order opportunities match; realized
fills, exposure and holding durations can differ after the shared constraints.

Each run uses the drawn symbol's own `2 * ATR20`, the selected variant's holding
limit, the five-position cap, 0.25% risk / 20% notional sizing, actual-fill close
stops, costs, recorded doubled slippage and T+1 cash. Existing holdings remain
eligible for drawing; repeat orders are ignored by the engine as usual. Final
marked equity minus starting capital, including open holdings, must **strictly
exceed the random 95th percentile**. The strategy's own orders are replayed and
must exactly reproduce its fills and equity before the comparison can run.
Only successful use of this full baseline lifts `random_portfolio: CAN'T TELL`.
Families still using the independent-trade sampler retain that blocker.

Validated prices, session opens/closes and ATR are prepared once, with fresh
portfolio state per run. The recorded development benchmark (100 symbols × 2,700 daily
sessions) took 105.9 seconds for 1,000 sequential runs plus 12.6 seconds of
baseline preparation/replay on the development machine, using one process.
Reproduce with `.venv/bin/python tests/benchmark_random_portfolio.py`; all
invented benchmark data stays in tests. See the
[build handoff](research/2026-11-05-earnings-reaction-build.md) for timing
and remaining limitations.

Point-in-time NIFTY 100 membership and dividend cash handling are also still
unavailable; imported symbols form a fixed universe. No claim of an edge is
made by this implementation.

Reports contain inline CSS, Python-generated SVG and local JavaScript, with
no external URLs or resources. Select chart points with a click or Enter to
highlight fills in the ledger. The layout supports 360-pixel screens and the
system dark-mode preference. No server is needed.
