# Oracle Autopsy

A local, CPU-only Python tool for researching Indian-market strategies and
checking their accounting. It never places orders.

Task 1 provides validated `Fill` and `RunRecord` types and a reference ledger.
`replay(fills, prices, start_cash)` applies already executed fills at their bar
timestamps, deducts their fees, and marks signed whole-share positions at each
bar's close. It returns cash, holdings value, equity, and independent position
snapshots for each distinct timestamp. If a symbol has no bar at a timestamp,
its last observed close is carried forward; future prices are never used.
Unmatched fills and duplicate symbol/time bars are rejected. Aware timestamps
are converted to Asia/Kolkata; naive timestamps are rejected.

Execution, settlement, costs, research selection and verdict checks are included.
The CLI currently exposes only the Task 9 historical-data fetch command; the
broader research/report CLI remains a later task.

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
later case study.

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
and preserves the schedule. Snapshots require a schedule or `bar_interval`.

For corporate actions, use this explicit separation:

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

The minimal CLI is `autopsy data fetch-upstox --symbols <text-file> --from
<YYYY-MM-DD> [--to <YYYY-MM-DD>]`: one cash instrument key per line; defaults to
five-minute bars through yesterday IST. Missing/rejected/expired tokens give
setup instructions and exit 2 without a traceback. Tests use only invented
candles and `httpx.MockTransport`; they never contact Upstox.
