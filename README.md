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

Nothing here has been run on real market data yet; that needs an Upstox
Analytics Token. Paper only: it never places
orders, and none of it is investment advice.

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

Login starts a listener bound only to `127.0.0.1:8742`, prints the login URL,
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
