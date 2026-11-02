from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from autopsy.types import Fill, RunRecord


def make_fill(**overrides):
    fields = dict(
        time=pd.Timestamp("2026-01-05 09:15", tz="Asia/Kolkata"),
        symbol="SYNTH", side="BUY", qty=10, price=100.0, fee=3.0,
    )
    return Fill(**(fields | overrides))


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError, match="tz-aware"):
        make_fill(time=pd.Timestamp("2026-01-05 09:15"))


def test_missing_timestamp_rejected():
    with pytest.raises(ValueError, match="tz-aware"):
        make_fill(time=pd.NaT)


def test_aware_timestamp_normalized_to_ist():
    fill = make_fill(time=pd.Timestamp("2026-01-05 03:45", tz="UTC"))
    assert str(fill.time.tz) == "Asia/Kolkata"
    assert fill.time.hour == 9 and fill.time.minute == 15


@pytest.mark.parametrize("qty", [0, -1, 1.5, 1.0, True])
def test_quantity_must_be_positive_integer(qty):
    with pytest.raises(ValueError, match="qty"):
        make_fill(qty=qty)


def test_numpy_integer_quantity_accepted():
    assert make_fill(qty=np.int64(2)).qty == 2


@pytest.mark.parametrize("overrides", [
    {"side": "HOLD"}, {"symbol": ""}, {"price": 0},
    {"price": float("nan")}, {"fee": -1}, {"fee": float("inf")},
])
def test_invalid_fill_rejected(overrides):
    with pytest.raises(ValueError):
        make_fill(**overrides)


def test_fill_is_frozen():
    with pytest.raises(FrozenInstanceError):
        make_fill().qty = 20


def test_run_record_preserves_data_and_normalizes_indices():
    index = pd.date_range("2026-01-05 03:45", periods=1, tz="UTC")
    prices = pd.DataFrame(dict(
        symbol=["SYNTH"], open=[100], high=[100], low=[100],
        close=[100], volume=[1000],
    ), index=index)
    equity = pd.Series([9997.0], index=index)
    fills = [make_fill()]
    record = RunRecord(fills, equity, prices, 10_000.0)
    assert record.fills == fills
    assert record.start_cash == 10_000.0
    assert record.reported_equity.iloc[0] == 9997.0
    assert str(record.prices.index.tz) == "Asia/Kolkata"
    assert str(record.reported_equity.index.tz) == "Asia/Kolkata"
    assert str(prices.index.tz) == str(equity.index.tz) == "UTC"


@pytest.mark.parametrize("naive_field", ["prices", "reported_equity"])
def test_run_record_rejects_naive_indices(naive_field):
    index = pd.date_range("2026-01-05 09:15", periods=1, tz="Asia/Kolkata")
    prices = pd.DataFrame(dict(
        symbol=["SYNTH"], open=[100], high=[100], low=[100],
        close=[100], volume=[1000],
    ), index=index)
    equity = pd.Series([10_000.0], index=index)
    target = prices if naive_field == "prices" else equity
    target.index = target.index.tz_localize(None)
    with pytest.raises(ValueError, match="tz-aware"):
        RunRecord([], equity, prices, 10_000.0)
