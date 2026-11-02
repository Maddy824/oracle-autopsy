import numpy as np
import pandas as pd
import pytest

from autopsy.checks.ledger_check import check_ledger
from autopsy.costs import load_rates
from autopsy.engine import Signal, run_backtest
from autopsy.ledger import replay
from autopsy.types import Fill, RunRecord
from autopsy.adapters.gym import record_gym_run


def prices():
    return pd.DataFrame({
        "symbol": "SYNTH", "open": 100.0, "high": 100.0, "low": 100.0,
        "close": 100.0, "volume": 1000,
    }, index=pd.date_range("2026-01-05 09:15", periods=10, freq="5min", tz="Asia/Kolkata"))


def test_mismatch_located():
    bars = prices()
    fills = [Fill(bars.index[2], "SYNTH", "BUY", 5, 100.0, 1.0),
             Fill(bars.index[7], "SYNTH", "SELL", 5, 100.0, 1.0)]
    equity = replay(fills, bars, 1000.0).equity
    equity.iloc[7:] += 500.0
    result = check_ledger(RunRecord(fills, equity, bars, 1000.0))
    assert result.verdict == "FAIL"
    assert result.evidence["first_bad_bar"] == 7
    assert result.evidence["gap"] == 500.0
    assert result.evidence["fills_since_previous_bar"] == [fills[1]]


def test_clean_record_passes():
    bars = prices()
    record = run_backtest(bars, [Signal(bars.index[0], "SYNTH", 1)], "intraday",
                          slippage_bps=0, rates=load_rates("zerodha"))
    assert record.fills
    assert check_ledger(record).verdict == "PASS"


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_flat_round_trip_loses_only_fees(side):
    bars = prices()
    fills = [Fill(bars.index[0], "SYNTH", side, 5, 100.0, 1.0),
             Fill(bars.index[-1], "SYNTH", "SELL" if side == "BUY" else "BUY", 5, 100.0, 2.0)]
    equity = replay(fills, bars, 1000.0).equity
    assert equity.iloc[-1] == 997.0
    record = RunRecord(fills, equity, bars, 1000.0)
    assert check_ledger(record).verdict == "PASS"
    record.reported_equity.iloc[-1] = 1000.0
    assert check_ledger(record).verdict == "FAIL"


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_nonfinite_equity_never_passes(bad):
    bars = prices()
    equity = pd.Series(1000.0, index=bars.index)
    equity.iloc[3] = bad
    result = check_ledger(RunRecord([], equity, bars, 1000.0))
    assert result.verdict == "FAIL"
    assert result.evidence["first_bad_bar"] == 3


def test_missing_equity_cannot_pass():
    bars = prices()
    result = check_ledger(RunRecord([], pd.Series(1000.0, index=bars.index[1:]), bars, 1000.0))
    assert result.verdict == "CAN'T TELL"


@pytest.mark.parametrize("tol", [-1, np.nan, np.inf])
def test_invalid_tolerance(tol):
    bars = prices()
    with pytest.raises(ValueError, match="tol"):
        check_ledger(RunRecord([], pd.Series(1000.0, index=bars.index), bars, 1000.0), tol)


def test_tolerance_is_absolute_and_inclusive():
    bars = prices()
    record = RunRecord([], pd.Series(1_000_000.125, index=bars.index), bars, 1_000_000.0)
    assert check_ledger(record, tol=0.125).verdict == "PASS"
    assert check_ledger(record, tol=0.124).verdict == "FAIL"


@pytest.mark.parametrize("end_flag", ["terminated", "truncated"])
def test_gym_adapter_records_reset_and_terminal_fills(end_flag):
    class Env:
        audit_prices = prices()
        initial_balance = 1000.0

        def reset(self):
            self.bar = 0
            self.equity = self.initial_balance
            return "reset observation", {"fills": []}

        def step(self, action):
            assert action == 7
            self.bar += 1
            self.equity -= 2.0
            fills = [Fill(self.audit_prices.index[self.bar], "SYNTH", "BUY", 1, 100.0, 2.0)]
            return "terminal observation", 99999, end_flag == "terminated", end_flag == "truncated", {"fills": fills}

    seen = []

    def policy(obs, step):
        seen.append((obs, step))
        return 7

    env = Env()
    record = record_gym_run(env, policy, lambda _env, info: info["fills"],
                            lambda env, _info: (env.audit_prices.index[env.bar], env.equity))
    assert seen == [("reset observation", 0)]
    assert len(record.prices) == len(record.reported_equity) == 2
    assert len(record.fills) == 1
    assert record.reported_equity.tolist() == [1000.0, 998.0]
    assert check_ledger(record).verdict == "PASS"
