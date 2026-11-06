# Oracle Autopsy

My old trading bot turned ₹10,000 into ₹1,60,000 on a market that never moved.
This repo is the tool I built to find out why, and to stop it happening again.

It is a local, CPU-only Python tool that tests intraday and swing strategies on
the Indian market (NSE) and refuses to say GO unless the result survives:

- **An independent ledger.** Every fill is replayed with its own cash and
  holdings. On the old bot the books diverge at bar 11 (+₹10,000 from nowhere).
- **A look-ahead check.** It re-runs each strategy on truncated data; any
  signal that changes when the future is removed fails.
- **Real Indian costs.** STT, exchange charges, SEBI fee, stamp duty, GST and
  brokerage from a dated rate table, with slippage doubled at the final gate.
- **A sealed final year.** Research happens on earlier data. The last 12
  months are hash-locked and can be opened once.
- **Luck checks.** A block-bootstrap lower bound above zero, and a result above
  the 95th percentile of 1,000 random-entry runs. Under 30 trades is CAN'T TELL.

It also watches the market in paper mode. During market hours it sends buy and
sell alerts for the 15-minute opening-range breakout to my Mac and Telegram,
logs every paper fill, and scores the day in the evening against random entries.

```sh
autopsy case oracle --report out/oracle-report.html   # the bug autopsy
autopsy alerts replay --days 60 --out out/alerts.html  # paper alerts on invented prices
```

On invented random prices with a liquid stock's volatility, the alerts score
**FAIL** on every seed tried (203 paper trades on seed 17, −₹13,562 after ₹8,616
of costs): random prices have no edge, and costs make that visible. On data with
an edge planted in it, they score **PASS**. The tool can tell the two apart.

Paper only: it never places orders, and none of it is investment advice.

## Use it yourself

You need Python 3.11+, a Zerodha account with a Kite Connect app (₹500/month)
for prices, and NSE results files you download by hand. No market data is in
this repo, and none should be committed.

```sh
git clone https://github.com/Maddy824/oracle-autopsy && cd oracle-autopsy
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]' && pytest -q

# 1. Prices: create ~/.config/oracle-autopsy/kite.json (see "Kite Connect data"), then
autopsy kite login                       # once a day, by hand; nothing is automated
autopsy data fetch-kite --symbols deploy/nifty100_2026-11-05.txt --from 2015-01-01 --interval day

# 2. Results dates: download CSVs yourself from NSE (see below), then
autopsy events import --kind financial_results ~/Downloads/CF-*.csv

# 3. Test the strategy; every run is logged and counted against you
autopsy research run --mode swing --strategy earnings_reaction --index-symbol "NSE:NIFTY 50"
```

**NSE results files.** NSE's terms forbid automated collection, so download
them in a browser and do not redistribute them:

- [Financial Results](https://www.nseindia.com/companies-listing/corporate-filings-financial-results)
  for quarters up to December 2024: Equity tab, Company empty, Period Ended
  *Quarterly*, Search By *F&O Securities*, Custom range one calendar year at a
  time, *Download (.csv)*.
- [Integrated Filing – Financials](https://www.nseindia.com/companies-listing/corporate-integrated-filing)
  for quarters from March 2025: Company empty, Custom range, *Download (.csv)*.

Import both together: the older files have no symbol column, so symbols come
from exact company-name matches in the newer file. Companies that do not match
are skipped and listed.

**Changing it for your own goal.** Strategies live in `src/autopsy/strategies/`
and are registered in `strategies/__init__.py`. Write the rules and parameter
grid down *before* you run anything on real data: the trial log, the sealed
final year and the random-portfolio check exist so that trying many ideas
until one looks good is visible and penalised. The NIFTY 100 list is today's
members, so every backtest on it has survivorship bias; reports say so.

## Daily brief and news

```sh
autopsy brief --notify telegram   # 18:30 market strip + 3 Economic Times headlines
autopsy news poll                 # archive new ET market headlines (run hourly)
```

The brief uses read-only Kite quotes: Nifty 50 and its 200-day regime, India
VIX, NIFTY 100 breadth and movers, three headlines, and the strategy status. If
the day's Kite login is missing it sends a reminder instead. Telegram needs
`~/.config/oracle-autopsy/telegram.json` (mode 600) with `bot_token` and
`chat_id`. Headlines are context only: they are archived with first-seen times
so they can become a pre-registered factor after a year, never used in
hindsight. Only sources whose terms allow personal storage are used; see
`docs/research/sources/2026-11-06-codex-factors-and-news.md`. To schedule on a
Mac, fill `__REPO__` and `__HOME__` in `deploy/com.oracleautopsy.brief.plist.example`
and `deploy/com.oracleautopsy.news.plist.example`, copy them to
`~/Library/LaunchAgents/` without `.example`, and `launchctl load` each.

## Internals

Task 1 provides validated `Fill` and `RunRecord` types and a reference ledger.
`replay(fills, prices, start_cash)` applies already executed fills at their bar
timestamps, deducts their fees, and marks signed whole-share positions at each
bar's close. It returns cash, holdings value, equity, and independent position
snapshots for each distinct timestamp. If a symbol has no bar at a timestamp,
its last observed close is carried forward; future prices are never used.
Unmatched fills and duplicate symbol/time bars are rejected. Aware timestamps
are converted to Asia/Kolkata; naive timestamps are rejected.

Execution, settlement, costs, research selection, verdict checks and an offline
HTML report are included. The CLI connects the complete local workflow.

Requires Python 3.11+:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

Keep private data, snapshots, event ledgers, trial logs, and lock files outside
this repository: `AUTOPSY_DATA_DIR` defaults to `~/oracle-autopsy-data`.
The Upstox client uses `~/.config/oracle-autopsy/upstox_analytics_token`
(mode 600). Never commit or print credentials or real NSE data. Tests use
synthetic data only. The optional `oracle` extra supplies `gymnasium` for the
Oracle case study.

## Paper alerts

```sh
autopsy alerts test-notify --notify console,mac
autopsy alerts replay --days 60 --out out/alerts.html            # invented prices
autopsy alerts live --symbols ~/oracle-autopsy-watchlist.txt --notify console,mac,telegram
autopsy alerts scorecard --out out/scorecard.html                # after the close
```

`live` polls Upstox's intraday candles 10 seconds after every five-minute
boundary until 15:16 IST, using the Analytics Token above. Copy
`deploy/watchlist.example.txt`, check each instrument key against Upstox's
instrument file, and keep it outside the repo. Telegram reads
`~/.config/oracle-autopsy/telegram.json` (mode 600) with `bot_token` and
`chat_id`; messages go to that one chat. `deploy/launchd.plist.template` starts
the watch at 09:10 on weekdays under `caffeinate`. The scorecard reports
CAN'T TELL until 60 sessions and 100 trades.

## Local workflow

```sh
autopsy data synthetic
autopsy research run --mode intraday
autopsy lock create
autopsy holdout open
autopsy report --out out/synthetic-report.html
autopsy case oracle --report out/oracle-report.html
```

Exit codes are 0 when no check is FAIL, 1 when any check is FAIL, and 2 for
setup errors. A NO-GO containing only CAN'T TELL checks exits 0. The seeded
random-walk demo and Oracle case intentionally produce NO-GO; continue to the
report command after the holdout command exits 1. Install `.[oracle]` to run
the copied Oracle case from this checkout.

The CLI demo uses 520 invented weekday sessions, 09:15–10:25 IST at five-minute
intervals, with seed 17. These short sessions keep the full CPU workflow quick;
they are not an NSE calendar or evidence about market returns. Research tries
the registered parameter and slippage grids on development folds, logs missing
event evidence as CAN'T TELL, and seals the last twelve calendar months. Each
opening is recorded; a second opening produces FAIL. Rendering a report does
not reopen the holdout. Locks refuse overlapping prior windows.

Import manually downloaded data with `autopsy data import-nse <csv…>` and
`autopsy events import <csv…>`; event imports also accept
`--kind bulk_deal` or `--kind block_deal`. Daily price files support swing
research (`--mode swing`), not intraday validation. Imported CSV copies,
snapshots, the session manifest, trial history, locks and evaluation records
all live under `AUTOPSY_DATA_DIR`.

An optional `research run --benchmark-symbol <symbol>` identifies a Nifty 50
ETF in the price input and excludes it from strategy trades. The report shows
its buy-and-hold curve normalized to the same capital, before ETF costs and
tax. Without ETF data, comparison is explicitly unavailable; synthetic prices
are never presented as real ETF observations. Gross/net and cost sensitivity
hold observed fills and quantities fixed. The verdict uses the actual run at
doubled slippage. The separate intraday business-income illustration defaults
to a 30% slab rate (`report --slab-rate 30` or the report's local input); swing
uses 20% STCG. Neither tax illustration changes a verdict.

### Pre-registered earnings reaction (daily swing)

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
portfolio state per run. The offline benchmark (100 symbols × 2,700 daily
sessions) took 105.9 seconds for 1,000 sequential runs plus 12.6 seconds of
baseline preparation/replay on the development machine, using one process.
Reproduce with `.venv/bin/python tests/benchmark_random_portfolio.py`; all
invented benchmark data stays in tests. See the
[build handoff](docs/research/2026-11-05-earnings-reaction-build.md) for timing
and remaining limitations.

Point-in-time NIFTY 100 membership and dividend cash handling are also still
unavailable; imported symbols form a fixed universe. No claim of an edge is
made by this implementation.

Reports contain inline CSS, Python-generated SVG and local JavaScript, with
no external URLs or resources. Select chart points with a click or Enter to
highlight fills in the ledger. The layout supports 360-pixel screens and the
system dark-mode preference. No server is needed.

## Upstox data

`synthetic_intraday(days, seed, pattern)` supplies invented five-minute sessions
(`random_walk`, `flat`, or `planted_orb`). `load_bhavcopy(paths)` imports manually
downloaded legacy or UDiFF NSE daily CSVs, using EQ rows. Daily file dates mean
midnight IST; timestamp inputs elsewhere must already be timezone-aware.
There is no NSE scraper. Unknown CSV columns are reported as errors.

Every loader attaches `prices.attrs['expected_bars']` as JSON text containing
`[ISO timestamp, symbol]` pairs. For each date observed in **any** symbol, the
schedule spans that day's earliest through latest bar across all symbols at
the dataset interval, for **every** dataset symbol. This covers interior gaps,
missing symbol-days, short sessions and evening sessions. It cannot detect an
entire day or session edge absent from every symbol. Preserve these attrs when
slicing research windows; use `autopsy.data.schedule.combine_prices` to merge
symbols/chunks and rebuild their joint schedule without discarding known gaps.

`save_snapshot(prices, 'raw'|'adjusted', source)` writes separate Parquet files
under `AUTOPSY_DATA_DIR`, with `.json` sidecars containing SHA-256, source and an
IST download timestamp. `load_snapshot(path)` checks the hash before parsing
and preserves the schedule and `price_basis`. Snapshots require a schedule or
`bar_interval`. CLI snapshots use `prices.attrs.get('price_basis', 'raw')` for
their kind; synthetic and NSE bhavcopy inputs remain raw.

Broker candles from **Upstox and Kite are already split/bonus-adjusted**, carry
`price_basis='adjusted'`, and must **NOT** be passed to `with_actions` or `adjust`:
that would adjust them twice. Dividends are not adjusted. Upstox has no raw
history option ([October 2026 clarification](https://community.upstox.com/t/clarification-on-upstox-historical-candle-v3-data-usage-for-personal-backtesting-and-ml-research/18061));
see also the [Kite adjustment discussion](https://kite.trade/forum/discussion/14381/in-historical-data-are-prices-adjusted-for-splits-and-bonus).

For genuinely raw data, such as NSE bhavcopy imports, use this explicit separation:

```python
from autopsy.data.corporate import adjust, with_actions

# actions: DataFrame with symbol, aware time, kind ('split'|'bonus'), ratio.
# Split ratio = new shares / old shares; bonus ratio = additional / old shares.
execution_prices = with_actions(raw, actions)  # raw OHLC plus share_multiplier
signal_prices = adjust(raw, actions)          # back-adjusted OHLC and volume
# Build strategy signals from signal_prices; run_backtest uses execution_prices.
```

The engine and reference ledger apply share multipliers before that bar's
fills, with no cash flow. Fractional entitlements raise an error until
cash-in-lieu data is available. Trade statistics and random-entry comparisons
honour those factors, and locked data hashes include them. Adjustment never
mutates the input; pass a complete action table for the supplied history.

`UpstoxClient.candles(instrument_key, unit, interval, start, end)` uses only the
V3 historical GET endpoint. Date-only `YYYY-MM-DD` bounds are inclusive. Its
module docstring links the official API and Analytics Token documentation and
records supported intervals, availability and request limits. All minute
requests use calendar-month chunks; HTTP 429 gets three retries after 1, 2 and
4 seconds. Verified request caches live under `AUTOPSY_DATA_DIR/upstox`.

The fetch command is `autopsy data fetch-upstox --symbols <text-file> --from
<YYYY-MM-DD> [--to <YYYY-MM-DD>]`: one cash instrument key per line; defaults to
five-minute bars through yesterday IST. Missing/rejected/expired tokens give
setup instructions and exit 2 without a traceback. Tests use only invented
candles and `httpx.MockTransport`; they never contact Upstox.

## Kite Connect data

Create a Connect app at [developers.kite.trade](https://developers.kite.trade/)
(₹500/month), with redirect URL **exactly** `http://127.0.0.1:8742/kite`. Static IP whitelisting is
only needed for order placement; historical data works from any IP. This
integration only reads data and exchanges login tokens; it has no order API.

Save the app credentials in `~/.config/oracle-autopsy/kite.json`:

```json
{"api_key": "YOUR_API_KEY", "api_secret": "YOUR_API_SECRET"}
```

Make the directory private and the credentials file mode 600:

```sh
chmod 700 ~/.config/oracle-autopsy
chmod 600 ~/.config/oracle-autopsy/kite.json
autopsy kite login
```

Login starts a listener bound only to `127.0.0.1:8742`
and opens the browser (`--no-browser` skips opening it). Log in manually on
**this Mac**; passwords and TOTP are never stored or automated. The redirect
is captured and exchanged immediately, and the tab says “Kite login saved.
You can close this tab.” No copy-paste is needed. Failed logins can be retried
while the listener waits. The request token is single-use and valid only a
few minutes. The CLI writes
`~/.config/oracle-autopsy/kite_session.json` atomically with mode 600, storing
`access_token`, `login_time` and `expires_at`. Both files must be mode 600 or
they are treated as missing. Run `autopsy kite login` daily: a session expires
at the next 06:00 IST (the same day's 06:00 if login was before then).
Use `--credentials PATH` and `--session PATH` on either command to override
the default paths. Login failures and missing/expired sessions exit 2 with
instructions and no traceback or token output.

Each listener checks a one-time random state returned by Kite and requires
the Host header to match `127.0.0.1:<port>` or `localhost:<port>`. Five invalid
state, status, token or exchange attempts end the wait with exit 2. The
state-bearing login URL is never printed; use `--paste` for manual login
when browser opening is disabled or unavailable.

Login options:

- `--wait 10m` sets the deadline (default 10 minutes; also accepts `90s`,
  `18h`, etc.). A timeout exits 2; run `autopsy kite login` again to retry.
- `--if-needed` exits immediately when the saved session is valid for at
  least another 30 minutes, without opening a browser or sending a reminder.
- `--notify` sends a Mac reminder and, if already configured in
  `~/.config/oracle-autopsy/telegram.json`, a Telegram reminder to log in
  **on this Mac, not a phone**. The browser tab opens ready for login unless
  `--no-browser` is supplied. Notification delivery is best effort.
- `--port 8742` changes the loopback port; a different port also requires
  changing the app's registered redirect URL to match.
- `--paste` restores the manual prompt: copy the **whole address-bar URL**
  after login, even if the browser shows a connection error. Use this if the
  listener port is busy. `--wait` applies to listener mode, not the paste prompt.

An optional weekday reminder template is provided at
`deploy/com.oracleautopsy.kite-login.plist.example`. It runs
`autopsy kite login --if-needed --notify --wait 17h` at **15:45 local Mac
time**, with logs under `~/oracle-autopsy-data/logs/`. It does not run research
or fetch data. The Mac must be awake and the owner logged in for timely
delivery; a saved session still expires at 06:00 IST, irrespective of the
listener's deadline. The template is not installed automatically.

To install, run from the repository root after creating `.venv`:

```sh
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/oracle-autopsy-data/logs"
agent="$HOME/Library/LaunchAgents/com.oracleautopsy.kite-login.plist"
cp deploy/com.oracleautopsy.kite-login.plist.example "$agent"
sed -i '' -e "s|__REPO__|$PWD|g" -e "s|__HOME__|$HOME|g" "$agent"
launchctl bootstrap "gui/$(id -u)" "$agent"
```

To uninstall:

```sh
agent="$HOME/Library/LaunchAgents/com.oracleautopsy.kite-login.plist"
launchctl bootout "gui/$(id -u)" "$agent"
rm "$agent"
```

```sh
autopsy data fetch-kite --symbols deploy/kite_symbols.example.txt \
  --from 2025-01-01 --interval 5minute
```

The symbols file has one `EXCHANGE:TRADINGSYMBOL` per line, with optional `#`
comments. For example, `NSE:RELIANCE` is an equity and `NSE:NIFTY 50` is the
index (including its space). `--to YYYY-MM-DD` defaults to yesterday IST;
today and future end dates are capped at yesterday. The client itself accepts
inclusive date-only bounds or timezone-aware timestamps without this CLI cap.

Intervals are `minute`, `3minute`, `5minute` (default), `10minute`, `15minute`,
`30minute`, `60minute`, and `day`. Requests use at most 59, 99, 99, 99, 199,
199, 399, and 1999 days respectively, one day below the service caps. Requests
are spaced at least 0.35 seconds apart; HTTP 429 retries wait 1, 2, and 4 seconds.
Instrument CSVs are cached per IST date under `AUTOPSY_DATA_DIR/kite`, and
symbols are resolved by exchange and trading symbol because tokens can be
reused. Candle chunks use SHA-256-verified Parquet caches there, without auth
in cache keys. Saved input snapshots have kind `adjusted`; do not apply
corporate-action adjustment again. Tests use invented data, local HTTP and
`httpx.MockTransport`; live authentication and data are not tested. Sandboxes
that deny loopback binding skip the three real-socket login tests; run the
suite in a normal local shell to exercise those tests.

Intraday research uses the same session window for every symbol and every
date: **bar start strictly before 15:15 IST**, including historical dates
before August 2026. Since 3 August 2026, F&O stocks' continuous session ends
at 15:15, so their last Kite five-minute bar starts at 15:10; indices and
non-F&O stocks can still have 15:15–15:25 bars. The common research window
excludes those extra bars and their `expected_bars` slots, avoiding three
false missing-bar flags per stock/day while retaining genuine earlier gaps.
The announced CAS move to 15:30–15:40 on 7 December 2026 does not change this
fixed convention.

Trimming occurs in `research run --mode intraday` before features, signals,
benchmark splitting and frozen research snapshots, so development backtests,
locks, holdouts and reports use the same window. Swing/daily research and
saved source snapshots remain unchanged. Direct Python backtest callers
should apply `autopsy.data.schedule.intraday_research_prices` before computing
signals; the general engine continues to accept supplied session shapes.
Intraday and swing selections with different frozen evidence cannot share a
lock; use separate `AUTOPSY_DATA_DIR` workflows for those modes.

The existing square-off rule therefore exits at **15:10 bar open**, with
adverse slippage, rather than its 15:15 closing price. This scheduled exit
does not read that bar's close; signals execute strictly on a later bar, and
entries at the cutoff are blocked. Short or incomplete sessions still use
their last observed bar, so expected-schedule quality checks remain necessary.
