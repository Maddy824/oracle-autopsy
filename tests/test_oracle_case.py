import pandas as pd
import pytest

pytest.importorskip("gymnasium", reason="Oracle case needs optional gymnasium")

from cases.oracle.run_case import (
    OracleFillExtractor, flat_prices, oracle_equity, oracle_features, run_oracle_case,
)
from autopsy.adapters.gym import record_gym_run
from autopsy.checks.lookahead import check_lookahead


@pytest.fixture(scope="module")
def case():
    return run_oracle_case()


def test_oracle_flat_market_makes_money(case):
    record = case["record"]
    assert case["ledger"].verdict == "FAIL"
    assert len(case["input_prices"]) == 500
    assert record.prices.close.eq(100.0).all()
    assert record.reported_equity.iloc[-1] > record.start_cash
    assert record.reported_equity.iloc[-1] == 160_000.0
    assert record.start_cash == 10_000.0
    assert case["ledger"].evidence["first_bad_bar"] == 11
    assert case["ledger"].evidence["first_bad_time"] == case["input_prices"].index[40].isoformat()
    assert [f.side for f in record.fills] == ["BUY", "SELL"] * 3 + ["SELL", "BUY"]
    assert [f.qty for f in record.fills] == [100, 100, 200, 200, 400, 400, 800, 800]
    assert all(record.prices.index.get_loc(b.time) - record.prices.index.get_loc(a.time) == 10
               for a, b in zip(record.fills[::2], record.fills[1::2]))
    assert case["reference_equity"].eq(record.start_cash).all()


def test_oracle_leak_found(case):
    assert case["lookahead"].verdict == "FAIL"
    assert "target_volatility_5d" in case["lookahead"].evidence["leaking_columns"]
    assert "target_volatility_5d" in case["observation_features"]


def test_oracle_drawdown_bug(case):
    assert case["oracle_drawdown"] == pytest.approx(-0.1111, abs=1e-4)
    assert case["true_drawdown"] == pytest.approx(-0.2)


def test_case_repeatable(case):
    again = run_oracle_case()
    pd.testing.assert_series_equal(case["record"].reported_equity, again["record"].reported_equity)
    assert case["record"].fills == again["record"].fills


def test_original_target_changes_when_future_prices_change():
    prices = flat_prices()
    changed = prices.copy()
    changed.iloc[100, changed.columns.get_loc("close")] = 120.0
    original = oracle_features(prices)
    altered = oracle_features(changed)
    assert original.target_volatility_5d.iloc[95] == 0.0
    assert altered.target_volatility_5d.iloc[95] > 0.0
    assert check_lookahead(oracle_features, changed).verdict == "FAIL"


def oracle_env(**kwargs):
    import warnings
    with warnings.catch_warnings():
        from cases.oracle.original.oracle_env import OracleTradingEnv
    prices = flat_prices()
    env = OracleTradingEnv(prices, slippage=0, max_position_size=1,
                           lookback_window=30, **kwargs)
    env.audit_prices = prices
    return env


def test_extractor_captures_forced_exit_and_real_fees():
    env = oracle_env(commission=0.001, stop_loss=0)
    extractor = OracleFillExtractor()
    try:
        env.reset()
        _, _, _, _, info = env.step(1)
        fills = extractor(env, info)
        assert [f.side for f in fills] == ["BUY", "SELL"]
        assert [f.fee for f in fills] == [10.0, 10.0]
        assert fills[0].time == fills[1].time == env.df.index[30]
        assert extractor(env, info) == []
    finally:
        env.close()


def test_extractor_captures_reversal_in_execution_order():
    env = oracle_env(commission=0.0)
    extractor = OracleFillExtractor()
    try:
        env.reset()
        *_, info = env.step(1)
        assert [f.side for f in extractor(env, info)] == ["BUY"]
        *_, info = env.step(3)
        fills = extractor(env, info)
        assert [f.side for f in fills] == ["SELL", "SELL"]
        assert [f.qty for f in fills] == [100, 200]
        assert fills[0].time == fills[1].time == env.df.index[31]
    finally:
        env.close()


def test_fractional_oracle_quantity_is_not_rounded():
    env = oracle_env(commission=0.0, initial_balance=10_050.0)
    try:
        with pytest.raises(ValueError, match="whole shares"):
            record_gym_run(env, lambda _obs, _step: 1, OracleFillExtractor(), oracle_equity)
    finally:
        env.close()


def test_cli_runs_the_case_from_any_folder(tmp_path):
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-m", "autopsy.cli", "case", "oracle"], cwd=tmp_path,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode != 2, result.stderr
    assert "ledger: FAIL at bar 11" in result.stdout
