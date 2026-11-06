"""Invented, offline portfolio null tests; small Monte Carlo counts in tests."""

from collections import Counter
import json

import numpy as np
import pandas as pd
import pytest

from autopsy.checks.ledger_check import check_ledger
from autopsy.data.schedule import with_schedule
from autopsy.costs import load_rates
from autopsy.engine import Signal, run_backtest
from autopsy.news.events import with_events
from autopsy.research.walkforward import Pick
from autopsy.stats import _EarningsPortfolio, random_portfolio_baseline
from autopsy.strategies import earnings_reaction as reaction
from autopsy.types import RunRecord
from autopsy import verdict as verdict_module
from test_earnings_reaction import INDEX, PARAMS, notice, prepared, simulate
from test_verdict import seal


def edge_market(edge, cycles=32):
    """Only A has results; its post-event drift is the planted selection edge."""
    size = 205 + cycles * 10
    times = pd.bdate_range("2023-01-02", periods=size, tz="Asia/Kolkata")
    event_days = np.arange(205, size - 7, 10)
    frames = []
    for symbol in ("A", "B", "C", "D", "E", "F", "G", "H"):
        returns = np.zeros(size)
        returns[event_days] = .01
        if edge and symbol == "A":
            for d in event_days:
                returns[d + 1:d + 6] = .025
        close = 100 * np.cumprod(1 + returns)
        opens = np.r_[100, close[:-1]]
        frames.append(pd.DataFrame({"symbol": symbol, "open": opens, "close": close,
                                    "high": np.maximum(opens, close) * 1.005,
                                    "low": np.minimum(opens, close) * .995,
                                    "volume": 10000}, index=times))
    prices = with_schedule(pd.concat(frames).sort_index(kind="stable"), "D")
    prices = with_events(prices, [notice("A", times[d] - pd.Timedelta(hours=7)) for d in event_days])
    prices.attrs.update(index_symbol=INDEX, index_prices=json.dumps(
        [[t.isoformat(), 100 + i * .01] for i, t in enumerate(times)]))
    return prices


@pytest.mark.parametrize("variant", reaction.VARIANTS)
def test_own_choices_exactly_reproduce_strategy_and_state_is_fresh(variant):
    prices, times = prepared(symbols=tuple("ABCDEFGH"))
    # Capacity rejections, a slipped gap entry, a close stop, and missing bars.
    prices.loc[(prices.symbol == "H") & (prices.index == times[206]), "open"] = 130
    prices.loc[(prices.symbol == "H") & (prices.index == times[207]), "close"] = 90
    prices = prices.loc[~((prices.symbol == "G") & (prices.index == times[206]))]
    record = simulate(prices, variant, slippage=20)
    plan = _EarningsPortfolio(record, {"variant": variant})
    for _ in range(2):
        fills, equity = plan.run(plan.strategy_signals)
        assert fills == record.fills
        pd.testing.assert_series_equal(equity, record.reported_equity, check_exact=True)
    held = set()
    for fill in record.fills:
        if fill.side == "BUY":
            held.add(fill.symbol)
        else:
            held.remove(fill.symbol)
        assert len(held) <= 5
    assert any(f.symbol == "H" and f.side == "SELL" and f.time == times[207] for f in record.fills)
    assert check_ledger(record).verdict == "PASS"


def test_draws_match_orders_seasons_own_atr_and_exclude_index():
    prices, times = prepared(symbols=tuple("ABCDEFGH"))
    # Exercise exclusion even if a caller leaves index bars in engine history.
    index_rows = prices.loc[prices.symbol == "A"].copy()
    index_rows["symbol"] = INDEX
    attrs = prices.attrs.copy()
    prices = pd.concat([prices, index_rows]).sort_index(kind="stable")
    prices.attrs = attrs
    # One symbol has no ATR warmup at D and must never be drawn.
    prices = prices.loc[~((prices.symbol == "H") & (prices.index < times[200]))]
    # Only A announces, but every warmed trading symbol is in the random pool.
    prices = with_events(prices, [notice("A", times[205] - pd.Timedelta(hours=7)),
                                notice("A", times[230] - pd.Timedelta(hours=7))])
    record = simulate(prices, slippage=20)
    plan = _EarningsPortfolio(record, PARAMS)
    features = reaction.features(prices, PARAMS)
    expected = Counter(s.time for s in plan.strategy_signals)
    assert expected == {times[205]: 1}  # event at 230 has no qualifying reaction
    rng = np.random.default_rng(19)
    seen = set()
    for _ in range(80):
        draws = plan.draw(rng)
        assert Counter(s.time for s in draws) == expected
        for signal in draws:
            seen.add(signal.symbol)
            row = features.loc[(features.index == signal.time) & (features.symbol == signal.symbol)].iloc[0]
            assert signal.risk_distance == 2 * row.atr20
            assert signal.holding_sessions == 10
    assert seen == set("ABCDEFG")
    assert INDEX not in seen


def test_draw_order_is_random_without_replacement_and_keeps_rejected_order_count():
    prices, times = prepared(symbols=tuple("ABCDEFGH"))
    record = simulate(prices, slippage=20)
    plan = _EarningsPortfolio(record, PARAMS)
    rng = np.random.default_rng(7)
    orders = plan.draw(rng)
    assert len(orders) == 8  # strategy submitted eight, even though only five fill
    assert len({s.symbol for s in orders}) == 8
    assert [s.priority for s in orders] == list(-np.arange(8))
    assert orders != plan.draw(rng)
    fills, curve = plan.run(orders)
    buys = [f for f in fills if f.side == "BUY"]
    assert [f.symbol for f in buys] == [s.symbol for s in orders[:5]]
    assert all(f.time == times[206] for f in buys)
    for fill, signal in zip(buys, orders):
        assert fill.qty == int(min(.2 * record.start_cash / fill.price,
                                   .0025 * record.start_cash / signal.risk_distance))
    assert check_ledger(RunRecord(fills, curve, prices, record.start_cash)).verdict == "PASS"


def test_seeds_and_open_position_metric():
    prices, times = prepared(symbols=("A", "B", "C"))
    # Keep open holdings at the right edge and change their terminal marks.
    prices = prices.loc[prices.index <= times[210]].copy()
    prices.loc[(prices.symbol == "A") & (prices.index == times[210]), "close"] = 160
    record = simulate(prices, slippage=20)
    result = random_portfolio_baseline(record, PARAMS, runs=7, seed=21)
    np.testing.assert_array_equal(result, random_portfolio_baseline(record, PARAMS, runs=7, seed=21))
    plan = _EarningsPortfolio(record, PARAMS)
    rng = np.random.default_rng(21)
    expected = [plan.run(plan.draw(rng))[1].iloc[-1] - record.start_cash for _ in range(7)]
    np.testing.assert_array_equal(result, expected)
    assert all(f.side == "BUY" for f in record.fills)
    # Three submitted orders draw all three symbols; use a one-order pool for seed variability.
    one = with_events(prices, [notice("A", times[205] - pd.Timedelta(hours=7))])
    single = simulate(one, slippage=20)
    assert not np.array_equal(random_portfolio_baseline(single, PARAMS, runs=12, seed=0),
                              random_portfolio_baseline(single, PARAMS, runs=12, seed=1))


def test_prepared_random_engine_enforces_fees_cash_and_t_plus_one():
    prices, times = prepared(symbols=tuple("ABCDEFGH"))
    prices["close"] = np.where(prices.index < times[205], 100., 100.1)
    prices.loc[prices.index == times[207], "close"] = 90.
    prices["open"] = prices.groupby("symbol").close.shift(1).fillna(100.)
    prices.loc[prices.index == times[206], "open"] = 100.
    prices["high"] = prices[["open", "close"]].max(axis=1) + .1
    prices["low"] = prices[["open", "close"]].min(axis=1) - .1
    record = simulate(prices, slippage=20)
    plan = _EarningsPortfolio(record, PARAMS)
    orders = plan.draw(np.random.default_rng(0))
    # All five positions consume the account, then stop on the 207 close.
    # Try new symbols on the liquidation open, and again after settlement.
    for s in orders[5:]:
        for day in (207, 208):
            orders.append(Signal(times[day], s.symbol, 1, risk_distance=1., holding_sessions=10))
    fills, curve = plan.run(orders)
    initial = [f for f in fills if f.side == "BUY" and f.time == times[206]]
    assert len(initial) == 5
    assert sum(f.qty * f.price + f.fee for f in initial) <= record.start_cash
    assert initial[-1].qty < initial[0].qty  # fees reduce the last allocation
    assert sum(f.side == "SELL" and f.time == times[208] for f in fills) == 5
    assert not any(f.side == "BUY" and f.time == times[208] for f in fills)
    assert sum(f.side == "BUY" and f.time == times[209] for f in fills) == 3
    public = run_backtest(prices, orders, "swing", slippage_bps=20, rates=load_rates("zerodha"))
    assert fills == public.fills
    pd.testing.assert_series_equal(curve, public.reported_equity, check_exact=True)
    assert check_ledger(public).verdict == "PASS"


def test_prepared_engine_preserves_share_actions_and_stop_rescaling():
    prices, times = prepared()
    prices["share_multiplier"] = 1.
    prices.loc[times[210], "share_multiplier"] = 2.
    prices.loc[prices.index >= times[210], ["open", "high", "low", "close"]] /= 2
    record = simulate(prices, slippage=20)
    plan = _EarningsPortfolio(record, PARAMS)
    fills, curve = plan.run(plan.strategy_signals)
    assert fills == record.fills
    assert fills[1].qty == 2 * fills[0].qty
    assert fills[1].time == times[217]  # split alone must not trigger the stop
    pd.testing.assert_series_equal(curve, record.reported_equity, check_exact=True)
    assert check_ledger(record).verdict == "PASS"


@pytest.mark.parametrize("edge", [True, False])
def test_planted_edge_beats_p95_but_no_edge_does_not(edge):
    prices = edge_market(edge, cycles=12)
    record = simulate(prices, "h5_regime", slippage=20)
    baseline = random_portfolio_baseline(record, {"variant": "h5_regime"}, runs=39, seed=0)
    profit = record.reported_equity.iloc[-1] - record.start_cash
    assert bool(profit > np.quantile(baseline, .95)) == edge


@pytest.mark.parametrize("bad", ["metadata", "record", "mode", "runs"])
def test_refuse_unverifiable_baselines(bad):
    prices, _ = prepared()
    record = simulate(prices, slippage=20)
    runs = 1
    if bad == "metadata":
        record.reported_equity.attrs.clear()
    elif bad == "record":
        record.reported_equity.iloc[-1] += 1
    elif bad == "mode":
        record.reported_equity.attrs["autopsy_execution"]["mode"] = "intraday"
    else:
        runs = 0
    with pytest.raises(ValueError):
        random_portfolio_baseline(record, PARAMS, runs=runs)


@pytest.mark.parametrize("failure,edge", [(False, True), (True, True), (False, False)])
def test_verdict_gate_lifted_only_after_full_baseline(tmp_path, monkeypatch, failure, edge):
    prices = edge_market(edge)
    pick = Pick("earnings_reaction", "swing", {"variant": "h5_regime"})
    record = simulate(prices, "h5_regime", slippage=20)
    calls = []

    def small_baseline(record, params, runs, seed):
        calls.append((runs, seed))
        if failure:
            raise ValueError("baseline unavailable")
        return random_portfolio_baseline(record, params, runs=19, seed=seed)

    def forbidden(*args, **kwargs):
        pytest.fail("earnings must never use legacy sampler")

    monkeypatch.setattr(verdict_module, "random_portfolio_baseline", small_baseline)
    monkeypatch.setattr(verdict_module, "random_entry_baseline", forbidden)
    result = verdict_module.decide(pick, record, [], seal(tmp_path, pick, prices))
    assert calls == [(1000, 0)]
    checks = {c.name: c.verdict for c in result.checks}
    assert checks["random_portfolio"] == ("CAN'T TELL" if failure else "PASS")
    assert checks["random_entry"] == ("CAN'T TELL" if failure else "PASS" if edge else "FAIL")
    assert result.verdict == ("GO" if edge and not failure else "NO-GO"), result
