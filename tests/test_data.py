import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from autopsy.checks.ledger_check import check_ledger
from autopsy.costs import load_rates
from autopsy.data.corporate import adjust, with_actions
from autopsy.data.nse import load_bhavcopy
from autopsy.data.schedule import combine_prices, with_schedule
from autopsy.data.store import load_snapshot, save_snapshot
from autopsy.data.synthetic import synthetic_intraday
from autopsy.engine import Signal, run_backtest
from autopsy.ledger import replay
from autopsy.research.lock import hash_prices
from autopsy.stats import _round_trips, random_entry_baseline
from autopsy.types import Fill, RunRecord
from autopsy.verdict import _data_check


def daily(values, symbol="SYNTH"):
    frame = pd.DataFrame({"symbol": symbol, **{k: values for k in
                         ("open", "high", "low", "close")}, "volume": 1000},
                         index=pd.date_range("2025-01-01", periods=len(values),
                                             tz="Asia/Kolkata", name="time"))
    return with_schedule(frame, "1D")


def test_snapshot_roundtrip_hash(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPSY_DATA_DIR", str(tmp_path))
    original = synthetic_intraday(2, 7, "random_walk")
    path = save_snapshot(original, "raw", "synthetic")
    restored, meta = load_snapshot(path)
    pd.testing.assert_frame_equal(original, restored)
    assert restored.attrs == original.attrs
    assert path.parent == tmp_path / "raw"
    assert meta["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert meta["source"] == "synthetic"
    assert pd.Timestamp(meta["downloaded_at"]).utcoffset().total_seconds() == 19800
    adjusted = save_snapshot(original, "adjusted", "synthetic")
    assert adjusted.parent == tmp_path / "adjusted"
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="hash"):
        load_snapshot(path)


def test_split_no_fake_jump():
    original = daily([100., 100., 50., 50.])
    actions = pd.DataFrame([{"symbol": "SYNTH", "time": original.index[2],
                             "kind": "split", "ratio": 2.}])
    raw = with_actions(original, actions)
    adjusted = adjust(original, actions)
    assert adjusted.close.tolist() == [50.] * 4
    assert adjusted.volume.tolist() == [2000., 2000., 1000., 1000.]
    assert original.close.tolist() == [100., 100., 50., 50.]
    fills = [Fill(raw.index[0], "SYNTH", "BUY", 10, 100., 0.),
             Fill(raw.index[-1], "SYNTH", "SELL", 20, 50., 0.)]
    record = RunRecord(fills, pd.Series(2000., index=raw.index), raw, 2000.)
    assert check_ledger(record).verdict == "PASS"
    ledger = replay(fills, raw, 2000.)
    assert ledger.positions.iloc[2] == {"SYNTH": 20}
    assert ledger.equity.tolist() == [2000.] * 4
    result = run_backtest(raw, [Signal(raw.index[0], "SYNTH", 1),
                               Signal(raw.index[2], "SYNTH", 0)],
                          "swing", slippage_bps=0, rates=load_rates("zerodha"))
    assert result.fills[-1].qty == 2 * result.fills[0].qty
    assert result.reported_equity.iloc[2] == result.reported_equity.iloc[1]
    assert check_ledger(result).verdict == "PASS"


def test_bhavcopy_both_layouts(tmp_path):
    old = tmp_path / "old.csv"
    old.write_text("SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,TIMESTAMP,ISIN\n"
                   "ALPHA,EQ,100,102,99,101,1000,01-JAN-2025,INVENTED\n")
    new = tmp_path / "new.csv"
    new.write_text("TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol,TradDt,FinInstrmId\n"
                   "ALPHA,EQ,101,103,100,102,2000,2025-01-02,1\n"
                   "BETA,EQ,50,52,49,51,3000,2025-01-02,2\n")
    frame = load_bhavcopy([new, old])
    assert frame.close.tolist() == [101., 102., 51.]
    assert str(frame.index.tz) == "Asia/Kolkata"
    expected = json.loads(frame.attrs["expected_bars"])
    assert len(expected) == 4  # BETA absent on the entire first day.
    assert [frame.index[0].isoformat(), "BETA"] in expected
    old.write_text(old.read_text().replace("OPEN", "UNRECOGNISED_PRICE"))
    with pytest.raises(ValueError, match="UNRECOGNISED_PRICE"):
        load_bhavcopy([old])


def test_schedule_union_grid_survives_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPSY_DATA_DIR", str(tmp_path))
    a = daily([100., 100.], "A")
    a.index = pd.DatetimeIndex(["2025-01-01 18:00", "2025-01-01 18:10"], tz="Asia/Kolkata")
    a = with_schedule(a, "5min")
    b = daily([50.], "B")
    b.index = pd.DatetimeIndex(["2025-01-02 13:00"], tz="Asia/Kolkata")
    b = with_schedule(b, "5min")
    frame = combine_prices([a, b])
    expected = json.loads(frame.attrs["expected_bars"])
    assert len(expected) == 8  # Three evening bars and one short-day bar, both symbols.
    assert ["2025-01-01T18:05:00+05:30", "B"] in expected
    lock = SimpleNamespace(locked_start=a.index[0].normalize(), locked_end=b.index[0] + pd.Timedelta(days=1))
    assert _data_check(frame, lock).evidence["missing_fraction"] == 5 / 8
    restored, _ = load_snapshot(save_snapshot(frame, "raw", "synthetic"))
    assert restored.attrs["expected_bars"] == frame.attrs["expected_bars"]


@pytest.mark.parametrize("pattern", ["flat", "random_walk", "planted_orb"])
def test_synthetic_deterministic_and_scheduled(pattern):
    frame = synthetic_intraday(3, 17, pattern)
    pd.testing.assert_frame_equal(frame, synthetic_intraday(3, 17, pattern))
    assert len(frame) == 3 * 75
    assert str(frame.index.tz) == "Asia/Kolkata"
    assert len(json.loads(frame.attrs["expected_bars"])) == len(frame)
    assert (frame.high >= frame[["open", "close"]].max(axis=1)).all()
    if pattern == "flat":
        assert frame.close.nunique() == 1
    lock = SimpleNamespace(locked_start=frame.index.min().normalize(),
                           locked_end=frame.index.max() + pd.Timedelta(days=1))
    assert _data_check(frame, lock).verdict == "PASS"
    assert _data_check(frame.iloc[10:], lock).verdict == "CAN'T TELL"


def test_bonus_and_split_compound_without_double_adjustment():
    raw = daily([120., 60., 40.])
    actions = pd.DataFrame([
        {"symbol": "SYNTH", "time": raw.index[1], "kind": "split", "ratio": 2.},
        {"symbol": "SYNTH", "time": raw.index[2], "kind": "bonus", "ratio": .5},
    ])
    adjusted = adjust(raw, actions)
    np.testing.assert_allclose(adjusted.close, 40.)
    annotated = with_actions(raw, actions)
    assert annotated.share_multiplier.tolist() == [1., 2., 1.5]
    pd.testing.assert_frame_equal(adjust(annotated, actions), adjusted)
    with pytest.raises(ValueError, match="adjusted"):
        with_actions(adjusted, actions)
    with pytest.raises(ValueError, match="whole.share"):
        replay([Fill(raw.index[1], "SYNTH", "BUY", 1, 60., 0.)], annotated, 100.)


def test_naive_times_rejected():
    raw = daily([100., 50.])
    naive = raw.copy()
    naive.index = naive.index.tz_localize(None)
    with pytest.raises(ValueError, match="tz-aware"):
        with_schedule(naive, "1D")
    actions = pd.DataFrame([{"symbol": "SYNTH", "time": pd.Timestamp("2025-01-02"),
                             "kind": "split", "ratio": 2.}])
    with pytest.raises(ValueError, match="tz-aware"):
        adjust(raw, actions)


def test_corporate_factors_are_locked():
    raw = daily([100., 50.])
    actions = pd.DataFrame([{"symbol": "SYNTH", "time": raw.index[1], "kind": "split", "ratio": 2.}])
    annotated = with_actions(raw, actions)
    before = hash_prices(annotated)
    annotated.loc[annotated.index[-1], "share_multiplier"] = 3.
    assert hash_prices(annotated) != before


def test_split_trade_counts_and_random_baseline():
    # All valid trades earn zero before costs, including those spanning the split.
    raw = daily([100.] * 62 + [50.] * 62)
    actions = pd.DataFrame([{"symbol": "SYNTH", "time": raw.index[62], "kind": "split", "ratio": 2.}])
    raw = with_actions(raw, actions)
    signals = [Signal(raw.index[i], "SYNTH", target)
               for i in range(0, 120, 4) for i, target in [(i, 1), (i + 2, 0)]]
    result = run_backtest(raw, signals, "swing", slippage_bps=0, rates=load_rates("zerodha"))
    assert len(_round_trips(result)) == 30
    baseline = random_entry_baseline(result, raw, runs=50, seed=7)
    assert (baseline < 0).all()
    assert (baseline > -5000).all()  # Fees only, no fictitious raw-price split loss/gain.


@pytest.mark.parametrize('basis', ['raw', 'adjusted'])
def test_price_basis_survives_combining_and_snapshot(tmp_path, monkeypatch, basis):
    monkeypatch.setenv('AUTOPSY_DATA_DIR', str(tmp_path))
    a, b = daily([100., 101.], 'A'), daily([200.], 'B')
    a.attrs['price_basis'] = b.attrs['price_basis'] = basis
    # Different schedules force pandas concat to discard attrs unless restored.
    assert a.attrs['expected_bars'] != b.attrs['expected_bars']
    combined = combine_prices([a, b])
    assert combined.attrs['price_basis'] == basis
    restored, meta = load_snapshot(save_snapshot(combined, basis, 'invented'))
    assert restored.attrs == combined.attrs
    assert meta['kind'] == basis
    b.attrs['price_basis'] = 'raw' if basis == 'adjusted' else 'adjusted'
    with pytest.raises(ValueError, match='raw and adjusted'):
        combine_prices([a, b])
