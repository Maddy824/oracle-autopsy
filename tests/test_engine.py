import pandas as pd
import pytest

from autopsy.calendar import trading_days
from autopsy.costs import load_rates, trade_costs
from autopsy.engine import Signal, run_backtest
from autopsy.ledger import replay


def bars(times, price=100.0, symbol="SYNTH"):
    return pd.DataFrame({
        "symbol": symbol, "open": price, "high": price, "low": price,
        "close": price, "volume": 1000,
    }, index=pd.DatetimeIndex(times, tz="Asia/Kolkata", name="time"))


@pytest.fixture
def rates():
    return load_rates("zerodha")


def test_next_bar_execution(rates):
    prices = bars(["2026-01-05 09:15", "2026-01-05 09:20", "2026-01-05 15:15"])
    prices.loc[prices.index[1], ["open", "high", "low", "close"]] = 123.0
    record = run_backtest(prices, [Signal(prices.index[0], "SYNTH", 1)],
                          "intraday", slippage_bps=0, rates=rates)
    assert record.fills[0].time == prices.index[1]
    assert record.fills[0].price == 123.0


def test_intraday_forced_flat_1515(rates):
    prices = bars([f"2026-01-05 {t}" for t in ["09:15", "09:20", "15:10", "15:17", "15:20"]])
    record = run_backtest(prices, [Signal(prices.index[0], "SYNTH", 1)],
                          "intraday", slippage_bps=0, rates=rates)
    ledger = replay(record.fills, prices, record.start_cash)
    assert ledger.positions.loc[prices.index[2]]["SYNTH"] > 0
    assert record.fills[-1].time == prices.index[3]
    assert ledger.positions.loc[prices.index[3]]["SYNTH"] == 0


def test_half_day_session(rates):
    prices = bars(["2026-01-05 09:15", "2026-01-05 09:20", "2026-01-05 13:00",
                   "2026-01-07 09:15", "2026-01-07 09:20", "2026-01-07 15:15"])
    record = run_backtest(prices, [Signal(prices.index[0], "SYNTH", 1)],
                          "intraday", slippage_bps=0, rates=rates)
    assert record.fills[-1].time == prices.index[2]
    assert trading_days(prices).equals(pd.DatetimeIndex(
        ["2026-01-05", "2026-01-07"], tz="Asia/Kolkata", name="time"))


def test_no_leverage(rates):
    prices = bars(["2026-01-05 09:15", "2026-01-05 09:20", "2026-01-05 15:15"], 3000.0)
    record = run_backtest(prices, [Signal(prices.index[0], "SYNTH", 1)],
                          "intraday", capital=200_000, slippage_bps=0, rates=rates)
    assert record.fills[0].qty == 66
    assert (replay(record.fills, prices, record.start_cash).cash >= 0).all()


def test_swing_max_five_positions(rates):
    prices = pd.concat([bars(["2026-01-05", "2026-01-06"], symbol=s) for s in "ABCDEF"])
    signals = [Signal(prices.index[0], s, 1) for s in "ABCDEF"]
    record = run_backtest(prices, signals, "swing", slippage_bps=0, rates=rates)
    assert [f.symbol for f in record.fills] == list("ABCDE")
    assert all(f.qty * f.price + f.fee <= 40_000 for f in record.fills)


def test_slippage_adverse(rates):
    prices = bars(["2026-01-05 09:15", "2026-01-05 09:20", "2026-01-05 15:15"])
    record = run_backtest(prices, [Signal(prices.index[0], "SYNTH", 1)],
                          "intraday", slippage_bps=25, rates=rates)
    assert [f.side for f in record.fills] == ["BUY", "SELL"]
    assert record.fills[0].price == 100 * (1 + 25 / 10_000)
    assert record.fills[1].price == 100 * (1 - 25 / 10_000)


@pytest.mark.parametrize("target", [-1, 1])
def test_entry_fees_fit_budget_and_equity_matches_reference(rates, target):
    prices = bars([f"2026-01-05 {t}" for t in ["09:15", "09:20", "15:15"]])
    original = prices.copy(deep=True)
    record = run_backtest(prices, [Signal(prices.index[0], "SYNTH", target)],
                          "intraday", slippage_bps=0, rates=rates)
    entry, exit_fill = record.fills
    assert entry.qty == exit_fill.qty == 1999
    assert entry.qty * entry.price + entry.fee <= record.start_cash
    assert entry.side == ("BUY" if target == 1 else "SELL")
    assert exit_fill.side != entry.side
    for fill in record.fills:
        assert fill.fee == trade_costs(
            fill.side, fill.qty * fill.price, "intraday_equity", rates,
        ).total
    assert record.reported_equity.iloc[-1] == pytest.approx(
        record.start_cash - sum(f.fee for f in record.fills))
    pd.testing.assert_series_equal(record.reported_equity,
                                   replay(record.fills, prices, record.start_cash).equity)
    pd.testing.assert_frame_equal(prices, original)


def test_delivery_fees_track_symbol_and_day(rates):
    times = [f"2026-01-05 {t}" for t in ["09:15", "09:20", "09:25", "09:30", "09:35"]]
    times += [f"2026-01-06 {t}" for t in ["09:15", "09:20", "09:25"]]
    a = bars(times, symbol="A")
    prices = pd.concat([a, bars(times, symbol="B")])
    signals = [Signal(a.index[i], "A", target) for i, target in
               [(0, 1), (1, 0), (2, 1), (3, 0), (5, 1), (6, 0)]]
    signals += [Signal(a.index[0], "B", 1), Signal(a.index[3], "B", 0)]
    record = run_backtest(prices, signals, "swing", slippage_bps=0, rates=rates)
    sold = set()
    dp = []
    assert len(record.fills) == 8
    for fill in record.fills:
        key = (fill.symbol, fill.time.normalize())
        costs = trade_costs(fill.side, fill.qty * fill.price, "delivery_equity",
                            rates, symbol_sold_today=key in sold)
        assert fill.fee == costs.total
        if fill.side == "SELL":
            sold.add(key)
            dp.append(costs.dp)
    assert dp == [15.34, 0, 15.34, 15.34]
    pd.testing.assert_series_equal(record.reported_equity,
                                   replay(record.fills, prices, record.start_cash).equity)


def test_delivery_proceeds_wait_until_next_observed_trading_day(rates):
    times = ["2026-01-09 09:15", "2026-01-09 09:20", "2026-01-09 09:25",
             "2026-01-12 09:15", "2026-01-12 09:20"]
    prices = pd.concat([bars(times, symbol=s) for s in "ABCDE"] +
                       [bars(times, price=3000.0, symbol="F")])
    index = prices.index.unique()
    signals = [Signal(index[0], s, 1) for s in "ABCDE"]
    signals += [Signal(index[1], "A", 0), Signal(index[1], "F", 1),
                Signal(index[2], "F", 1)]
    record = run_backtest(prices, signals, "swing", slippage_bps=0, rates=rates)
    assert [(f.time, f.side) for f in record.fills if f.symbol == "F"] == [(index[3], "BUY")]
    assert record.fills[-1].qty == 13
    pd.testing.assert_series_equal(record.reported_equity,
                                   replay(record.fills, prices, record.start_cash).equity)


def test_evening_special_session_exits_at_last_bar(rates):
    prices = bars([f"2026-01-05 {t}" for t in ["18:00", "18:05", "19:00"]])
    record = run_backtest(prices, [Signal(prices.index[0], "SYNTH", 1)],
                          "intraday", slippage_bps=0, rates=rates)
    assert [f.time for f in record.fills] == list(prices.index[1:])


def test_intraday_one_position_and_no_overnight_signal_or_cutoff_entry(rates):
    times = ["2026-01-05 09:15", "2026-01-05 09:20", "2026-01-05 15:10",
             "2026-01-05 15:15", "2026-01-06 09:15", "2026-01-06 15:15"]
    a = bars(times, symbol="A")
    prices = pd.concat([a, bars(times, symbol="B")])
    signals = [Signal(a.index[0], "A", -1), Signal(a.index[0], "B", 1),
               Signal(a.index[2], "B", 1), Signal(a.index[3], "A", 1)]
    record = run_backtest(prices, signals, "intraday", slippage_bps=10, rates=rates)
    assert [(f.symbol, f.side, f.time) for f in record.fills] == [
        ("A", "SELL", a.index[1]), ("A", "BUY", a.index[3])]
    assert record.fills[0].price == 100 * (1 - 10 / 10_000)
    assert record.fills[1].price == 100 * (1 + 10 / 10_000)


def test_symbol_specific_next_bar_and_deterministic_order(rates):
    a = bars(["2026-01-05 09:15", "2026-01-05 09:25", "2026-01-05 15:15"], symbol="A")
    b = bars(["2026-01-05 09:15", "2026-01-05 09:20", "2026-01-05 15:15"], symbol="B")
    prices = pd.concat([a, b])
    signals = [Signal(a.index[0], "A", 1), Signal(b.index[0], "B", 1)]
    record = run_backtest(prices, signals, "swing", slippage_bps=0, rates=rates)
    shuffled = run_backtest(prices.iloc[::-1], signals[::-1], "swing", slippage_bps=0, rates=rates)
    assert record.fills == shuffled.fills
    assert [(f.symbol, f.time) for f in record.fills] == [("B", b.index[1]), ("A", a.index[1])]
    pd.testing.assert_series_equal(record.reported_equity, shuffled.reported_equity)
    pd.testing.assert_series_equal(record.reported_equity,
                                   replay(record.fills, prices, record.start_cash).equity)


def test_target_is_direction_not_rebalance_and_reversal_closes_first(rates):
    prices = bars([f"2026-01-05 {t}" for t in ["09:15", "09:20", "09:25", "09:30", "15:15"]])
    signals = [Signal(prices.index[i], "SYNTH", target) for i, target in enumerate([1, 1, -1])]
    record = run_backtest(prices, signals, "intraday", slippage_bps=0, rates=rates)
    assert [(f.side, f.time) for f in record.fills] == [
        ("BUY", prices.index[1]), ("SELL", prices.index[3]),
        ("SELL", prices.index[3]), ("BUY", prices.index[4])]
    pd.testing.assert_series_equal(record.reported_equity,
                                   replay(record.fills, prices, record.start_cash).equity)


@pytest.mark.parametrize("mode", ["intraday", "swing"])
def test_empty_and_no_trade_runs(rates, mode):
    empty = bars([])
    record = run_backtest(empty, [], mode, slippage_bps=0, rates=rates)
    assert record.fills == []
    assert record.reported_equity.empty
    assert trading_days(empty).empty
    prices = bars(["2026-01-05 09:15", "2026-01-05 15:15"])
    for signals, capital in [([], 200_000), ([Signal(prices.index[0], "SYNTH", 1)], 1),
                              ([Signal(prices.index[-1], "SYNTH", 1)], 200_000)]:
        record = run_backtest(prices, signals, mode, capital, slippage_bps=0, rates=rates)
        assert record.fills == []
        assert (record.reported_equity == capital).all()


@pytest.mark.parametrize("target", [2, 0.5, True])
def test_invalid_signal_target_rejected(target):
    with pytest.raises(ValueError, match="target"):
        Signal(pd.Timestamp("2026-01-05", tz="Asia/Kolkata"), "SYNTH", target)


def test_naive_signal_and_calendar_rejected():
    with pytest.raises(ValueError, match="tz-aware"):
        Signal(pd.Timestamp("2026-01-05"), "SYNTH", 1)
    prices = bars(["2026-01-05"])
    prices.index = prices.index.tz_localize(None)
    with pytest.raises(ValueError, match="tz-aware"):
        trading_days(prices)


def test_swing_short_rejected(rates):
    prices = bars(["2026-01-05", "2026-01-06"])
    with pytest.raises(ValueError, match="long only"):
        run_backtest(prices, [Signal(prices.index[0], "SYNTH", -1)],
                     "swing", slippage_bps=0, rates=rates)


@pytest.mark.parametrize("slippage", [-1, float("nan"), float("inf"), 10_000])
def test_invalid_slippage_rejected(rates, slippage):
    with pytest.raises(ValueError, match="slippage"):
        run_backtest(bars(["2026-01-05"]), [], "swing", slippage_bps=slippage, rates=rates)


def test_duplicate_or_unknown_signal_rejected(rates):
    prices = bars(["2026-01-05", "2026-01-06"])
    signal = Signal(prices.index[0], "SYNTH", 1)
    with pytest.raises(ValueError, match="duplicate"):
        run_backtest(prices, [signal, signal], "swing", slippage_bps=0, rates=rates)
    with pytest.raises(ValueError, match="unknown symbol"):
        run_backtest(prices, [Signal(prices.index[0], "MISSING", 1)],
                     "swing", slippage_bps=0, rates=rates)
