# Market data and broker setup

## Optional real-market workflow

First complete the [offline quickstart](../README.md). For this optional
real-data example, you need a Zerodha account with a Kite Connect app for
prices and NSE results files downloaded manually. No market data is bundled
and none should be committed.

```sh
# From the checkout, with .venv activated. Keep this separate from demos.
export AUTOPSY_DATA_DIR="$HOME/oracle-autopsy-data"

# 1. Prices: create ~/.config/oracle-autopsy/kite.json (see setup below), then
autopsy kite login                       # manual broker login
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
until one looks good is visible in the trial history. The bundled NIFTY 100
list is a dated snapshot of members, so historical backtests on it have
survivorship bias; reports say so.

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
(check current pricing and terms there), with redirect URL **exactly** `http://127.0.0.1:8742/kite`. Static IP whitelisting is
only needed for order placement; historical data works from any IP. This
integration only reads data and exchanges login tokens; it has no order API.

Save the app credentials in `~/.config/oracle-autopsy/kite.json`:

```json
{"api_key": "YOUR_API_KEY", "api_secret": "YOUR_API_SECRET"}
```

Make the directory private and the credentials file mode 600:

```sh
mkdir -p ~/.config/oracle-autopsy
chmod 700 ~/.config/oracle-autopsy
chmod 600 ~/.config/oracle-autopsy/kite.json
autopsy kite login
```

Login starts a listener bound only to `127.0.0.1:8742`
and opens the browser (`--no-browser` skips opening it). Log in manually on
**the computer running the listener**; passwords and TOTP are never stored or automated. The redirect
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
that deny loopback binding skip the real-socket login tests; run the
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
