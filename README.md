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

Signal execution, settlement/available-cash rules, costs, and the CLI are future
tasks. The declared console entry point is reserved for that later CLI.

Requires Python 3.11+:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

Keep private data, snapshots, event ledgers, trial logs, and lock files outside
this repository: `AUTOPSY_DATA_DIR` defaults to `~/oracle-autopsy-data`.
The future Upstox client uses `~/.config/oracle-autopsy/upstox_analytics_token`
(mode 600). Never commit or print credentials or real NSE data. Tests use
synthetic data only. The optional `oracle` extra supplies `gymnasium` for the
later case study.
