# Oracle case provenance

Copy date: **2026-11-02**. Read-only source project:
`/Users/maddy/CascadeProjects/oracle-trading-system`.

| Local copy | Original source | Copy scope |
| --- | --- | --- |
| `original/oracle_env.py` | `/Users/maddy/CascadeProjects/oracle-trading-system/environment/oracle_env.py` | Entire file, byte-for-byte |
| `original/metrics.py` | `/Users/maddy/CascadeProjects/oracle-trading-system/utils/metrics.py` | Entire file, byte-for-byte |
| `original/features.py` | `/Users/maddy/CascadeProjects/oracle-trading-system/data/ingestion/main.py` | `AlphaDataPipeline.add_alpha_factors`, lines 92–288, byte-for-byte including indentation; minimal imports, logger and class shell in a clearly marked added header |

The original files and their bugs are unchanged. No source project configuration,
training pipeline, downloaded data or model weights are copied.

## Reproduction

From the repository root, with the optional `gymnasium` dependency installed:

```sh
.venv/bin/python -m cases.oracle.run_case
.venv/bin/python -m pytest -q
```

The case uses **500 synthetic daily bars at a flat price of 100.0**, starting
2025-01-01 at midnight Asia/Kolkata. Open, high, low and close are all 100.0;
volume is an invented constant 1000. These dates do not represent an exchange
calendar. TFT **`ctx_0` and `ctx_1` columns are zero-filled placeholders**. No TFT,
torch or machine learning is used.

The scripted policy opens longs at policy steps 0, 20 and 40 and closes each
10 bars later. It opens one short at step 60 and covers at step 70, then holds
through the remaining episode. Oracle's actual action meanings are 0 hold,
1 buy, 2 close long, 3 short, 4 cover. They are read from `_execute_action`.

Constructor choices: initial balance 10,000, lookback 30, commission 0,
slippage 0, maximum position fraction 1.0, simple reward; all other defaults
are retained. Zero costs and full allocation keep every executed quantity
integral (100, 200, 400, 800), matching Autopsy's whole-share contract without
rounding or changing Oracle's sizing code. These are bug-demonstration settings,
not the Indian cost model or a realistic strategy evaluation.

The adapter records `env.equity`, not rewards or balance-derived estimates.
Fills come from the actual `current_trade` and completed `trades`, including
entry/exit prices, direction, quantities and commissions. This also captures
forced closes and reversals. Fractional quantities are explicitly rejected.
`balance`, signed `position` (-1/0/1), `position_size` and `entry_price` retain
their original meanings. Oracle marks equity before incrementing
`current_step`; the recorded timestamp is therefore `df.index[current_step-1]`.
After reset, that timestamp identifies the last warmup bar (source bar 29).
Oracle truncates after executing source bar 498. The record has 470 observations,
including the reset baseline, and does not fabricate values for unused bars.

## Feature audit without pandas_ta

The original target lives inside a large method that also builds unrelated
technical indicators using `pandas_ta`, absent from this offline environment.
The entire method is preserved verbatim. `oracle_features` parses that copy
and compiles only its original `log_return` and `target_volatility_5d`
assignments, the complete dependency slice for this target. It does not import
or emulate `pandas_ta`, or rewrite the target formula. This audit covers that
target, not every indicator in the copied method.

The prefix audit uses those exact expressions on the synthetic data, retaining
NaNs: removing future bars changes historical target values from zero to NaN.
A separate test perturbs a future price and proves a historical target changes
numerically too. The environment gets the target column, and its real feature
selector includes it because its name contains `volatility`. Its constructor's
NaN-to-zero fill remains unchanged; auditing only that filled flat series would
hide the leak.

## Findings and handoff

- Reported final equity: **160,000.0**, versus **10,000.0** initially.
  Independent cash-and-shares replay stays at **10,000.0** throughout.
- First bad bar: **11** (zero-based in the recorded series), source bar **40**,
  **2025-02-10T00:00:00+05:30**, the first long exit. Reported equity is 20,000,
  reference equity 10,000, gap **+10,000**. The preceding entry's equity matches:
  Oracle treats balance as collateral while a trade is open, then wrongly adds
  principal at close. Its short close also credits value rather than debiting
  the cost of covering. See original environment lines 366–368 and 411.
- The target uses future returns (`shift(-5)`, original ingestion line 267),
  then reaches observations through the indicator selector (environment
  lines 156–160). The look-ahead check returns FAIL and names the target.
- On the separate declining probe `[100, 90, 80]`, Oracle's copied metric gives
  approximately **-0.111111**, versus **-0.2** when the initial peak is included.
  The original metric starts its cumulative curve after the first loss
  (metrics line 66). The correct comparison is computed locally in this case;
  Task 7's statistics module has not been started.
- Oracle's zero-profit trades also expose a divide-by-zero/invalid division
  warning in its profit-factor metric (environment line 735). This is retained.
  Its import-time global warning suppression is contained by the loader so it
  cannot suppress unrelated test warnings.

Scope ends at Task 5. No git commands, source-project edits, downloads, push,
deployment or Task 6 work. The shared SecondBrain vault is outside this session's
writable roots and no Basic Memory tool is available; this local handoff records
the decisions for the owner to carry into the project note and ACTIVE_STATE.
