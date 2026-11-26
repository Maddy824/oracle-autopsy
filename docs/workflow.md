# Strategy research and development

## Full offline research workflow

This part of the [quickstart](../README.md) exercises development selection,
sealing, the one-time holdout and
report rendering. It is CPU-only and uses invented prices. Run from the
checkout with the virtual environment activated; create a fresh private data
directory for each demonstration so prior locks and trial logs are not reused.

```sh
export AUTOPSY_DATA_DIR="$(mktemp -d)"
autopsy data synthetic
autopsy research run --mode intraday
autopsy lock create
autopsy holdout open || [ "$?" -eq 1 ]
autopsy report --out out/synthetic-report.html || [ "$?" -eq 1 ]
```

Exit codes are 0 when no check is FAIL, 1 when any check is FAIL, and 2 for
setup errors. A NO-GO containing only CAN'T TELL checks exits 0. The seeded
random-walk demo and Oracle case intentionally produce NO-GO; continue to the
report command after the holdout command exits 1. Do not repeat the holdout
opening in the same workflow. A new synthetic
directory is fine for a demo, not a way to repeat a sealed real-data experiment.

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

See the [earnings-reaction implementation](earnings-reaction.md) for its
pre-registered daily swing strategy and portfolio baseline.

## Internals

The package provides validated `Fill` and `RunRecord` types and a reference ledger.
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
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check
```

Keep private data, snapshots, event ledgers, trial logs, and lock files outside
this repository: `AUTOPSY_DATA_DIR` defaults to `~/oracle-autopsy-data`.
The Upstox client uses `~/.config/oracle-autopsy/upstox_analytics_token`
(mode 600). Never commit or print credentials or real NSE data. Tests use
synthetic data only. The optional `oracle` extra supplies `gymnasium` for the
Oracle case study; the `dev` extra includes it so the full suite runs.
