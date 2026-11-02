import numpy as np
import pandas as pd
import pytest
from hypothesis import given, strategies as st

from autopsy.ledger import replay
from autopsy.types import Fill


def bars(closes, symbol="SYNTH"):
    return pd.DataFrame({
        "symbol": symbol, "open": closes, "high": closes, "low": closes,
        "close": closes, "volume": 1000,
    }, index=pd.date_range(
        "2026-01-05 09:15", periods=len(closes), freq="5min", tz="Asia/Kolkata",
        name="time",
    ))


def test_flat_round_trip_loses_exactly_fees():
    prices = bars([100.0] * 3)
    fills = [
        Fill(prices.index[0], "SYNTH", "BUY", 10, 100.0, 3.0),
        Fill(prices.index[2], "SYNTH", "SELL", 10, 100.0, 4.0),
    ]
    ledger = replay(fills, prices, 10_000.0)
    assert ledger.equity.iloc[-1] == 9993.0
    assert ledger.cash.tolist() == [8997.0, 8997.0, 9993.0]
    assert ledger.holdings_value.tolist() == [1000.0, 1000.0, 0.0]
    np.testing.assert_allclose(ledger.cash + ledger.holdings_value, ledger.equity)


def test_short_round_trip():
    prices = bars([100.0, 95.0, 90.0])
    fills = [
        Fill(prices.index[0], "SYNTH", "SELL", 10, 100.0, 0.0),
        Fill(prices.index[2], "SYNTH", "BUY", 10, 90.0, 0.0),
    ]
    ledger = replay(fills, prices, 10_000.0)
    assert ledger.cash.iloc[0] == 11_000.0
    assert ledger.holdings_value.iloc[0] == -1000.0
    assert ledger.positions.iloc[0] == {"SYNTH": -10}
    assert ledger.equity.tolist() == [10_000.0, 10_050.0, 10_100.0]


@given(st.lists(st.tuples(
    st.integers(1, 100_000), st.integers(1, 100_000),
    st.integers(-20, 20), st.integers(0, 1000),
), min_size=1, max_size=40))
def test_equity_identity_property(steps):
    prices = bars([close / 100 for close, _, _, _ in steps])
    fills = [
        Fill(time, "SYNTH", "BUY" if delta > 0 else "SELL",
             abs(delta), execution / 100, fee / 100)
        for time, (_, execution, delta, fee) in zip(prices.index, steps)
        if delta
    ]
    ledger = replay(fills, prices, 100_000.0)
    np.testing.assert_allclose(
        ledger.cash + ledger.holdings_value, ledger.equity, rtol=0, atol=1e-9,
    )
    # Independent integer-paise accounting also catches wrong signs or lost fills.
    cash_paise, position = 10_000_000, 0
    for row, (close, execution, delta, fee) in zip(ledger.itertuples(), steps):
        if delta:
            cash_paise -= delta * execution + fee
            position += delta
        assert row.cash == pytest.approx(cash_paise / 100, rel=0, abs=1e-9)
        assert row.equity == pytest.approx(
            (cash_paise + position * close) / 100, rel=0, abs=1e-9,
        )
        assert row.positions.get("SYNTH", 0) == position


def test_multiple_symbols_and_fills_at_same_time():
    a, b = bars([100.0, 110.0], "A"), bars([50.0, 40.0], "B")
    prices = pd.concat([b, a]).iloc[::-1]
    original = prices.copy(deep=True)
    fills = [
        Fill(a.index[1], "A", "SELL", 1, 110.0, 1.0),
        Fill(a.index[0], "A", "BUY", 2, 100.0, 1.0),
        Fill(a.index[0], "B", "SELL", 3, 50.0, 2.0),
    ]
    ledger = replay(fills, prices, 1000.0)
    assert ledger.index.equals(a.index)
    assert ledger.cash.tolist() == [947.0, 1056.0]
    assert ledger.holdings_value.tolist() == [50.0, -10.0]
    assert ledger.equity.tolist() == [997.0, 1046.0]
    assert ledger.positions.tolist() == [{"A": 2, "B": -3}, {"A": 1, "B": -3}]
    ledger.positions.iloc[1]["A"] = 99
    assert ledger.positions.iloc[0]["A"] == 2
    pd.testing.assert_frame_equal(prices, original)


def test_no_fills_keeps_starting_cash():
    ledger = replay([], bars([100.0, 200.0]), 1234.0)
    assert ledger.equity.tolist() == [1234.0, 1234.0]
    assert ledger.holdings_value.tolist() == [0.0, 0.0]
    assert ledger.positions.tolist() == [{}, {}]


def test_empty_prices_returns_empty_ledger():
    ledger = replay([], bars([]), 1000.0)
    assert ledger.empty
    assert ledger.columns.tolist() == ["cash", "holdings_value", "equity", "positions"]
    assert str(ledger.index.tz) == "Asia/Kolkata"


@pytest.mark.parametrize("kind", ["off_bar", "unknown_symbol", "after_end"])
def test_unmatched_fill_rejected(kind):
    prices = bars([100.0])
    time, symbol = prices.index[0], "SYNTH"
    if kind == "off_bar":
        time += pd.Timedelta(minutes=1)
    elif kind == "after_end":
        time += pd.Timedelta(days=1)
    else:
        symbol = "UNKNOWN"
    with pytest.raises(ValueError, match="bar"):
        replay([Fill(time, symbol, "BUY", 1, 100.0, 0.0)], prices, 1000.0)


def test_duplicate_symbol_bar_rejected():
    prices = bars([100.0])
    with pytest.raises(ValueError, match="duplicate"):
        replay([], pd.concat([prices, prices]), 1000.0)


def test_missing_symbol_bar_uses_last_observed_close():
    a = bars([100.0, 110.0, 120.0], "A").iloc[[0, 2]]
    b = bars([50.0, 60.0, 70.0], "B")
    ledger = replay([Fill(a.index[0], "A", "BUY", 1, 100.0, 0.0)],
                    pd.concat([a, b]), 1000.0)
    assert ledger.equity.tolist() == [1000.0, 1000.0, 1020.0]


@pytest.mark.parametrize("problem", ["naive", "missing_column", "nan_close"])
def test_invalid_prices_rejected(problem):
    prices = bars([100.0])
    if problem == "naive":
        prices.index = prices.index.tz_localize(None)
    elif problem == "missing_column":
        prices = prices.drop(columns="volume")
    else:
        prices.loc[:, "close"] = float("nan")
    with pytest.raises(ValueError):
        replay([], prices, 1000.0)


@pytest.mark.parametrize("start_cash", [float("nan"), float("inf"), -1.0])
def test_invalid_start_cash_rejected(start_cash):
    with pytest.raises(ValueError, match="start_cash"):
        replay([], bars([100.0]), start_cash)
