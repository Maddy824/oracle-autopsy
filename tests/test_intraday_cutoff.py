import json
from types import SimpleNamespace

import pandas as pd
import pytest

from autopsy.costs import load_rates
from autopsy.data.schedule import intraday_research_prices, with_schedule
from autopsy.engine import Signal, run_backtest
from autopsy.verdict import _data_check


def mixed_prices():
    frames = []
    # Include historical full sessions and the newer stock/index mismatch.
    for day in ["2025-08-01", "2025-08-02", "2025-08-03", "2025-08-04",
                "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"]:
        for symbol in ["INDEX", "STOCK"]:
            end = "15:10" if symbol == "STOCK" and day.startswith("2026") else "15:25"
            index = pd.date_range(f"{day} 15:00", f"{day} {end}", freq="5min",
                                  tz="Asia/Kolkata", name="time")
            frames.append(pd.DataFrame({"symbol": symbol, "open": 100., "high": 110.,
                                        "low": 90., "close": 105., "volume": 1000}, index=index))
    prices = with_schedule(pd.concat(frames), "5min")
    prices.attrs["price_basis"] = "adjusted"
    return prices


def coverage(prices):
    return _data_check(prices, SimpleNamespace(
        locked_start=prices.index.min().normalize(),
        locked_end=prices.index.max().normalize() + pd.Timedelta(days=1)))


def test_common_intraday_window_preserves_source_and_removes_only_auction_gaps():
    prices = mixed_prices()
    original = prices.copy(deep=True)
    assert coverage(prices).evidence["missing_fraction"] > 0
    result = intraday_research_prices(prices)
    assert coverage(result).verdict == "PASS"
    assert coverage(result).evidence["missing_fraction"] == 0
    assert result.groupby(["symbol", result.index.normalize()]).size().eq(3).all()
    assert list(result.index.strftime("%H:%M").unique()) == ["15:00", "15:05", "15:10"]
    assert len(json.loads(result.attrs["expected_bars"])) == len(result)
    assert result.attrs["price_basis"] == "adjusted"
    pd.testing.assert_frame_equal(prices, original)
    assert prices.attrs == original.attrs


def test_trim_keeps_genuine_missing_session_edge_and_uses_ist():
    prices = mixed_prices()
    missing = pd.Timestamp("2026-11-05 15:10", tz="Asia/Kolkata")
    prices = prices.loc[prices.index != missing].copy()
    prices.index = prices.index.tz_convert("UTC")
    result = intraday_research_prices(prices)
    expected = json.loads(result.attrs["expected_bars"])
    assert [missing.isoformat(), "STOCK"] in expected
    assert [missing.isoformat(), "INDEX"] in expected
    assert coverage(result).evidence["missing_fraction"] == 2 / 48
    assert str(result.index.tz) == "Asia/Kolkata"


def test_cutoff_exit_fills_at_open_without_using_cutoff_close():
    prices = intraday_research_prices(mixed_prices())
    prices = prices.loc[(prices.symbol == "INDEX")
                        & (prices.index.normalize() == prices.index.min().normalize())].copy()
    prices.loc[prices.index[-1], ["open", "high", "close"]] = [102., 500., 499.]
    signal = Signal(prices.index[0], "INDEX", 1)
    record = run_backtest(prices, [signal], "intraday", slippage_bps=0,
                          rates=load_rates("zerodha"))
    assert [(fill.time.strftime("%H:%M"), fill.side, fill.price) for fill in record.fills] == [
        ("15:05", "BUY", 100.), ("15:10", "SELL", 102.)]
    changed = prices.copy()
    changed.loc[changed.index[-1], "close"] = 91.
    rerun = run_backtest(changed, [signal], "intraday", slippage_bps=0,
                         rates=load_rates("zerodha"))
    assert rerun.fills == record.fills
    pd.testing.assert_series_equal(rerun.reported_equity, record.reported_equity)


def test_research_with_only_excluded_bars_exits_cleanly(tmp_path, monkeypatch, capsys):
    from autopsy import cli

    monkeypatch.setenv("AUTOPSY_DATA_DIR", str(tmp_path))
    prices = mixed_prices()
    cli._save_inputs(prices.loc[prices.index.strftime("%H:%M") >= "15:15"], "invented late bars")
    assert cli.main(["research", "run", "--mode", "intraday"]) == 2
    err = capsys.readouterr().err
    assert 'No intraday bars start before 15:15 IST' in err and 'Traceback' not in err


@pytest.mark.parametrize("mode,interval", [("intraday", "5min"), ("swing", "5min"), ("swing", "1D")])
def test_research_filters_before_signals_and_freezes_only_research_copy(tmp_path, monkeypatch,
                                                                      mode, interval):
    from autopsy import cli
    from autopsy.data.store import load_snapshot
    from autopsy.research.walkforward import Pick

    monkeypatch.setenv("AUTOPSY_DATA_DIR", str(tmp_path))
    prices = mixed_prices()
    if interval == "1D":
        prices = prices.loc[prices.index.strftime("%H:%M") == "15:25"].copy()
        prices = with_schedule(prices, "1D")
    cli._save_inputs(prices, "invented mixed sessions")
    source_path = cli._state()["prices_path"]
    source, _ = load_snapshot(source_path)
    strategy = next(s for s in cli.REGISTRY.values() if s.mode == mode and not s.data_check)
    monkeypatch.setattr(cli, "REGISTRY", {strategy.name: strategy})
    pick = Pick(strategy.name, mode, {})
    seen = []

    def folds(strategy, research_prices, start, *, trial_log):
        seen.append(research_prices.copy())
        trial_log.append(strategy.name, {}, ["2025-08-01", "2025-09-01"], {"test": True})
        return [object()]

    monkeypatch.setattr(cli, "walk_forward", folds)
    monkeypatch.setattr(cli, "select", lambda _: pick)
    assert cli.main(["research", "run", "--mode", mode]) == 0
    research, _ = load_snapshot(cli._state()["selections"][mode]["snapshot"])
    expected = intraday_research_prices(source) if mode == "intraday" else source
    pd.testing.assert_frame_equal(seen[0], expected)
    pd.testing.assert_frame_equal(research, expected)
    assert research.attrs["expected_bars"] == expected.attrs["expected_bars"]
    assert cli.main(["lock", "create"]) == 0
    locked, _ = load_snapshot(cli._state()["locked_snapshot"])
    expected_locked = expected.loc[expected.index.year == 2026]
    pd.testing.assert_frame_equal(locked, expected_locked)
    assert locked.attrs["expected_bars"] == expected.attrs["expected_bars"]
    raw_after, _ = load_snapshot(source_path)
    pd.testing.assert_frame_equal(raw_after, source)
    assert raw_after.attrs == source.attrs
