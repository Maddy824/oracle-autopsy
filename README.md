# Oracle Autopsy

Local, CPU-only NSE strategy backtesting and paper alerts, with checks for impossible profits and look-ahead bias.

My old trading bot turned ₹10,000 into ₹1,60,000 on a market that never moved. Replaying its fills against an independent ledger exposed money appearing from nowhere; the code also leaked future volatility into its features and understated drawdown. I built Oracle Autopsy to catch those failures before trusting a backtest.

**Paper only. Never places orders. Not investment advice.**

## 60-second offline quickstart

Clone with `git clone https://github.com/Maddy824/oracle-autopsy.git` and `cd oracle-autopsy`, or download the repository. From its root, with Python 3.11 installed (or a newer supported Python; use its executable):

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[oracle]'
autopsy case oracle --report out/oracle-report.html || [ "$?" -eq 1 ]
(
  export AUTOPSY_DATA_DIR="$(mktemp -d)"
  autopsy data synthetic
  autopsy research run --mode intraday
  autopsy lock create
  autopsy holdout open || [ "$?" -eq 1 ]
  autopsy report --out out/synthetic-report.html || [ "$?" -eq 1 ]
  autopsy alerts replay --source synthetic --days 60 --seed 17 --out out/alerts.html
)
```

Measured at 54 seconds from a fresh virtual environment on a Mac with Python 3.11, including package installation (download speeds vary). Installation needs internet access for Python packages. All three runs are offline: no market-data download, broker account, KYC, API token or GPU. Open `out/oracle-report.html`, `out/synthetic-report.html` and `out/alerts.html` in your browser; no server is needed.

Actual terminal output (from the seeded demonstration):

```text
NO-GO
ledger: FAIL at bar 11
lookahead: FAIL
drawdown: FAIL
Selected vwap_revert (intraday) using development folds only. Lifetime trials: 84.
NO-GO
lock: PASS
random_entry: FAIL
FAIL: 203 paper trades over 60 sessions, net ₹-13,561.71 after ₹8,615.99 costs. Page: out/alerts.html
```

The Oracle case deliberately finds bugs in the copied environment (an original profit-factor warning may also appear). The strategy test selects on invented development data and evaluates a sealed final year; random prices are not evidence of a trading edge. Exit 1 means at least one check failed, as expected in these demos; exit 2 means a setup error. Each run uses a new temporary research directory, so it does not disturb existing locks or trial logs. Never reopen a sealed real-data holdout to try to get a better result.

The replay tests the 15-minute opening-range breakout on invented random-walk prices, including Indian execution costs and 1,000 random-entry runs. Its FAIL is the scorecard result, not a setup error.

## What it checks

- **Accounting:** an independent cash-and-shares ledger replays fills.
- **Look-ahead:** features are compared against truncated inputs at up to 20 sampled time cutoffs; signals are not audited directly.
- **Indian execution costs:** dated brokerage and statutory charge tables, with doubled slippage for the sealed research verdict.
- **Research discipline:** chronological development folds, a hash-locked final 12 months with one permitted opening, trial history, minimum-trade and block-bootstrap checks, and random-entry comparisons. Insufficient evidence is CAN'T TELL, not GO.

Historical market data and point-in-time index membership are not bundled. Fixed stock universes can introduce survivorship bias; dividend cash flows are not modeled. Missing benchmarks and incomplete random-portfolio evidence are reported explicitly. A GO is a research result, not a recommendation or guarantee.

## Go further

| What you want to do | Guide |
| --- | --- |
| Run the full offline research workflow, seal a final year and generate a report | [Strategy research and development](docs/workflow.md) |
| Understand the old environment and reproduce its bugs | [Oracle case provenance](cases/oracle/ORIGIN.md) |
| Import NSE CSVs or optionally use read-only Kite / Upstox market data | [Market data and broker setup](docs/market-data.md) |
| Use the paper alert replay, live paper watch or daily brief | [Paper alerts and daily brief](docs/paper-alerts.md) |
| Understand the earnings-reaction strategy and its limitations | [Earnings reaction](docs/earnings-reaction.md) |
| Read dated research and pre-registered hypotheses | [Research notes](docs/research/) |

[50-second project demo](docs/demo/README.md) (includes a historical NO-GO research result).

## Develop

With the virtual environment active:

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check
```

MIT — [LICENSE](LICENSE). Bug reports and reproducible test cases are welcome.
