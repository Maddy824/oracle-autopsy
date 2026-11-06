"""Invented daily prices only; no real data or services."""

from collections import Counter
import json

import numpy as np
import pandas as pd
import pytest

from autopsy import cli, verdict as verdict_module
from autopsy.checks.ledger_check import check_ledger
from autopsy.checks.lookahead import check_lookahead
from autopsy.costs import load_rates
from autopsy.data.schedule import with_schedule
from autopsy.engine import run_backtest
from autopsy.research.trials import TrialLog
from autopsy.research.walkforward import Pick, slippage_grid_for, walk_forward
from autopsy.stats import _ManagedPortfolio, random_portfolio_baseline
from autopsy.strategies import REGISTRY
from autopsy.strategies import weekly_loser_reversal as reversal
from test_verdict import seal

INDEX = "NSE:NIFTY 50"
FAMILY = "weekly_loser_reversal"
PARAMS = {"variant": "h5"}


def market(changes=(-10, -8, -6, -4, -2, 0, 1, 2, 3, 4), count=45):
    times = pd.bdate_range("2023-01-02", periods=count, tz="Asia/Kolkata")
    frames = []
    for i, change in enumerate(changes):
        close = np.where(np.arange(count) >= 20, 100. + change, 100.)
        opens = np.r_[100., close[:-1]]
        frames.append(pd.DataFrame({"symbol": f"S{i:02}", "open": opens, "close": close,
                                    "high": np.maximum(opens, close) + 1,
                                    "low": np.minimum(opens, close) - 1, "volume": 1000}, index=times))
    prices = with_schedule(pd.concat(frames).sort_index(kind="stable"), "D")
    prices.attrs.update(index_symbol=INDEX, index_prices=json.dumps(
        [[t.isoformat(), 100.] for t in times]))
    return prices, times


def orders(prices, variant="h5"):
    params = {"variant": variant}
    return reversal.signals(prices, reversal.features(prices, params), params)


def simulate(prices, variant="h5", slippage=10):
    return run_backtest(prices, orders(prices, variant), "swing",
                        slippage_bps=slippage, rates=load_rates("zerodha"))


@pytest.mark.parametrize("variant", reversal.VARIANTS)
def test_prefix_invariance_and_completed_close_math(variant):
    prices, times = market()
    params = {"variant": variant}
    features = reversal.features(prices, params)
    row = features.loc[(features.index == times[20]) & (features.symbol == "S00")].iloc[0]
    assert row.r5 == pytest.approx(90 / 100 - 1)
    assert row.atr20 == pytest.approx((19 * 2 + 12) / 20)
    assert row.history_eligible and row.eligible
    assert check_lookahead(lambda p: reversal.features(p, params), prices, cutoffs=30).verdict == "PASS"
    for cutoff in (19, 20, 23, 30):
        prefix = prices.loc[prices.index <= times[cutoff]]
        pd.testing.assert_frame_equal(reversal.features(prefix, params), features.loc[prefix.index.unique()])
        assert orders(prefix, variant) == [s for s in orders(prices, variant) if s.time <= times[cutoff]]
        assert simulate(prefix, variant).fills == [f for f in simulate(prices, variant).fills if f.time <= times[cutoff]]


@pytest.mark.parametrize("changes,expected", [
    ((-1,) * 4, []), ((-1,) * 9, ["S00"]), ((-1,) * 10, ["S00", "S01"]),
    ((-1,) + (0,) * 9, ["S00"]), ((0,) * 10, []), ((1,) * 10, []),
    ((-5, -10, -10) + (-1,) * 12, ["S01", "S02", "S00"]),
])
def test_bottom_quintile_negative_only_and_alphabetical_ties(changes, expected):
    prices, times = market(changes)
    signals = [s for s in orders(prices) if s.time == times[20]]
    assert [s.symbol for s in signals] == expected
    assert [s.priority for s in signals] == sorted([s.priority for s in signals], reverse=True)
    assert all(s.priority > 0 and s.holding_sessions == 4 for s in signals)


@pytest.mark.parametrize("variant,holding", [("h5", 5), ("h10", 10)])
def test_exact_holding_exit_no_pyramiding_and_risk_sizing(variant, holding):
    prices, times = market()
    record = simulate(prices, variant)
    buys = [f for f in record.fills if f.side == "BUY"]
    sells = [f for f in record.fills if f.side == "SELL"]
    assert len(buys) == len(sells) == 2
    distances = {s.symbol: s.risk_distance for s in orders(prices, variant) if s.time == times[20]}
    for buy, sell in zip(buys, sells):
        assert buy.time == times[21] and sell.time == times[21 + holding]
        assert buy.qty == int(min(.2 * 200_000 / buy.price, .0025 * 200_000 / distances[buy.symbol]))
    assert check_ledger(record).verdict == "PASS"


@pytest.mark.parametrize("entry_stop", [False, True])
def test_frozen_strict_close_stop_sells_next_open(entry_stop):
    prices, times = market((-10,) + (0,) * 9)
    distance = next(s.risk_distance for s in orders(prices) if s.time == times[20])
    stop = 120 * 1.001 - distance
    prices.loc[(prices.symbol == "S00") & (prices.index == times[21]), ["open", "high", "low", "close"]] = [120, 121, 100, stop]
    breach = 21 if entry_stop else 22
    prices.loc[(prices.symbol == "S00") & (prices.index == times[breach]), "close"] = stop - .01
    prices.loc[(prices.symbol == "S00") & (prices.index == times[breach + 1]), "open"] = 110
    fills = simulate(prices).fills
    assert fills[0].time == times[21] and fills[0].price == pytest.approx(120 * 1.001)
    assert fills[1].time == times[breach + 1] and fills[1].price == pytest.approx(110 * .999)


def test_all_orders_submitted_capacity_rejection_is_not_queued():
    prices, times = market((-1,) * 30)
    # One losing day only: no new orders after D.
    prices.loc[prices.index > times[20], ["open", "close"]] = 100.
    signals = orders(prices)
    assert len(signals) == 6
    record = simulate(prices)
    buys = [f for f in record.fills if f.side == "BUY"]
    assert [f.symbol for f in buys] == [f"S{i:02}" for i in range(5)]
    assert all(f.time == times[21] for f in buys)
    plan = _ManagedPortfolio(record, PARAMS, FAMILY)
    draws = plan.draw(np.random.default_rng(7))
    assert len(draws) == len({s.symbol for s in draws}) == 6
    assert [s.priority for s in draws] == list(-np.arange(6))
    assert draws != plan.draw(np.random.default_rng(8))


def test_index_excluded_even_when_present_in_bars():
    prices, times = market((-1,) * 9)
    index_rows = prices.loc[prices.symbol == "S00"].copy()
    index_rows["symbol"] = INDEX
    index_rows.loc[times[20]:, "close"] = 50.
    attrs = prices.attrs.copy()
    prices = pd.concat([index_rows, prices]).sort_index(kind="stable")
    prices.attrs = attrs
    features = reversal.features(prices, PARAMS)
    assert not features.loc[features.symbol == INDEX, "history_eligible"].any()
    assert [s.symbol for s in orders(prices) if s.time == times[20]] == ["S00"]
    record = simulate(prices)
    plan = _ManagedPortfolio(record, PARAMS, FAMILY)
    assert all(symbol != INDEX for _, _, pool in plan.pools for symbol, _ in pool)


@pytest.mark.parametrize("column,value", [("open", 0), ("high", -1), ("low", 0),
                                          ("volume", 0), ("volume", np.nan), ("high", np.inf)])
def test_positive_finite_21_bar_history_required(column, value):
    prices, times = market()
    prices.loc[(prices.symbol == "S00") & (prices.index == times[5]), column] = value
    features = reversal.features(prices, PARAMS)
    stock = features.loc[features.symbol == "S00"]
    assert not stock.loc[:times[25], "history_eligible"].any()
    assert stock.loc[times[26], "history_eligible"]


def test_insufficient_missing_history_and_zero_atr_excluded():
    prices, times = market()
    prices = prices.loc[~((prices.symbol == "S00") & (prices.index == times[5]))]
    prices = prices.loc[~((prices.symbol == "S01") & (prices.index < times[10]))]
    prices.loc[prices.symbol == "S02", ["open", "high", "low", "close"]] = 100.
    features = reversal.features(prices, PARAMS)
    for symbol, ready in (("S00", 26), ("S01", 30)):
        stock = features.loc[features.symbol == symbol]
        assert not stock.loc[:times[ready - 1], "history_eligible"].any()
        assert stock.loc[times[ready], "history_eligible"]
    assert not features.loc[features.symbol == "S02", "history_eligible"].any()


@pytest.mark.parametrize("variant", reversal.VARIANTS)
def test_random_replay_eligibility_own_atr_and_seed(variant):
    prices, times = market()
    prices = prices.loc[~((prices.symbol == "S09") & (prices.index < times[10]))]
    prices.loc[(prices.symbol == "S08") & (prices.index == times[10]), "volume"] = 0
    # No future bar for S07 at D: it must still be eligible for a random draw.
    prices = prices.loc[prices.index <= times[20]]
    record = simulate(prices, variant, slippage=20)
    params = {"variant": variant}
    plan = _ManagedPortfolio(record, params, FAMILY)
    features = reversal.features(prices, params)
    seen = set()
    rng = np.random.default_rng(19)
    for _ in range(80):
        draws = plan.draw(rng)
        assert Counter(s.time for s in draws) == Counter(s.time for s in plan.strategy_signals)
        for signal in draws:
            seen.add(signal.symbol)
            row = features.loc[(features.index == signal.time) & (features.symbol == signal.symbol)].iloc[0]
            assert row.history_eligible and signal.risk_distance == 2 * row.atr20
            assert signal.holding_sessions == reversal.VARIANTS[variant]
    assert seen == {f"S{i:02}" for i in range(8)}
    # Full record exercises real fills, stops/holding and fresh portfolio state.
    prices, _ = market()
    record = simulate(prices, variant, slippage=20)
    plan = _ManagedPortfolio(record, params, FAMILY)
    for _ in range(2):
        fills, equity = plan.run(plan.strategy_signals)
        assert fills == record.fills
        pd.testing.assert_series_equal(equity, record.reported_equity, check_exact=True)
    result = random_portfolio_baseline(record, params, runs=7, seed=21, family=FAMILY)
    np.testing.assert_array_equal(result, random_portfolio_baseline(record, params, runs=7, seed=21, family=FAMILY))
    rng = np.random.default_rng(21)
    np.testing.assert_array_equal(result, [plan.run(plan.draw(rng))[1].iloc[-1] - record.start_cash for _ in range(7)])
    record.reported_equity.iloc[-1] += 1
    with pytest.raises(ValueError, match="replay does not match"):
        random_portfolio_baseline(record, params, runs=1, family=FAMILY)


def edge_market(edge, cycles=20):
    prices, times = market((0,) * 10, count=25 + cycles * 15)
    for i in range(2 if edge else 10):
        returns = np.zeros(len(times))
        for day in range(20, len(times) - 6, 15):
            returns[day] = -.03
            if edge:
                returns[day + 1:day + 6] = .025
            else:
                # Identical stocks recover before the executable open: no
                # selection edge, and strategy/null have identical turnover.
                returns[day + 1] = 1 / .97 - 1
        close = 100 * np.cumprod(1 + returns)
        opens = np.r_[100, close[:-1]]
        if not edge:
            for day in range(20, len(times) - 6, 15):
                opens[day + 1] = close[day + 1]
        prices.loc[prices.symbol == f"S{i:02}", ["open", "high", "low", "close"]] = np.column_stack(
            [opens, np.maximum(opens, close) * 1.005, np.minimum(opens, close) * .995, close])
    return prices


@pytest.mark.parametrize("edge", [True, False])
def test_planted_reversal_passes_random_gate_no_edge_fails(tmp_path, monkeypatch, edge):
    prices = edge_market(edge)
    record = simulate(prices, slippage=20)
    calls = []

    def small_baseline(record, params, runs, seed, *, family):
        calls.append((runs, seed, family))
        return random_portfolio_baseline(record, params, runs=39, seed=seed, family=family)

    def forbidden(*args, **kwargs):
        pytest.fail("weekly losers must never use the legacy sampler")

    monkeypatch.setattr(verdict_module, "random_portfolio_baseline", small_baseline)
    monkeypatch.setattr(verdict_module, "random_entry_baseline", forbidden)
    pick = Pick(FAMILY, "swing", PARAMS)
    result = verdict_module.decide(pick, record, [], seal(tmp_path, pick, prices))
    assert calls == [(1000, 0, FAMILY)]
    checks = {check.name: check.verdict for check in result.checks}
    assert checks["random_portfolio"] == "PASS"
    assert checks["random_entry"] == ("PASS" if edge else "FAIL")
    assert result.verdict == ("GO" if edge else "NO-GO"), result


def test_registry_fixed_two_trials_and_slippage(tmp_path):
    strategy = REGISTRY[FAMILY]
    assert dict(strategy.params_grid) == {"variant": ("h5", "h10")}
    assert reversal.VARIANTS == {"h5": 4, "h10": 9}
    assert slippage_grid_for(strategy) == (10,)
    prices, times = market()
    log = TrialLog(tmp_path / "trials.jsonl")
    results = walk_forward(strategy, prices, times[-1], trial_log=log)
    assert log.trial_count == 2 and len(results) == 8
    assert all(row.slippage_bps == 20 for row in results)
    with pytest.raises(ValueError, match="slippage grid"):
        walk_forward(strategy, prices, times[-1], trial_log=log, slippage_grid=(5, 10))


@pytest.mark.parametrize("bad", ["interval", "duplicates", "index", "index_gap"])
def test_data_check_refuses_invalid_context(bad):
    prices, times = market()
    assert reversal.data_check(prices).verdict == "PASS"
    if bad == "interval":
        prices.attrs["bar_interval"] = "5min"
    elif bad == "duplicates":
        prices = pd.concat([prices, prices.iloc[:1]])
    elif bad == "index":
        del prices.attrs["index_symbol"]
    else:
        rows = json.loads(prices.attrs["index_prices"])
        prices.attrs["index_prices"] = json.dumps(rows[1:])
    assert reversal.data_check(prices).verdict == "CAN'T TELL"


def test_cli_requires_index_before_trials(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPSY_DATA_DIR", str(tmp_path))
    prices, _ = market()
    monkeypatch.setattr(cli, "_state", lambda: {})
    monkeypatch.setattr(cli, "_inputs", lambda state: prices)
    assert cli.main(["research", "run", "--mode", "swing", "--strategy", FAMILY]) == 2
    assert "requires --index-symbol" in capsys.readouterr().err
    assert TrialLog().trial_count == 0


def test_missing_scheduled_bar_makes_exact_session_evaluation_inconclusive(tmp_path):
    prices, times = market()
    prices = prices.loc[~((prices.symbol == "S00") & (prices.index == times[22]))]
    pick = Pick(FAMILY, "swing", PARAMS)
    result = verdict_module.decide(pick, simulate(prices, slippage=20), [], seal(tmp_path, pick, prices))
    check = next(check for check in result.checks if check.name == "data")
    assert 0 < check.evidence["missing_fraction"] < .02
    assert check.verdict == "CAN'T TELL" and result.verdict == "NO-GO"


@pytest.mark.parametrize("median", [0., -.1])
def test_cli_failed_development_keeps_holdout_sealed(tmp_path, monkeypatch, capsys, median):
    monkeypatch.setenv("AUTOPSY_DATA_DIR", str(tmp_path))
    prices, _ = market(count=400)
    index = prices.loc[prices.symbol == "S00"].copy()
    index["symbol"] = INDEX
    attrs = prices.attrs.copy()
    prices = pd.concat([prices, index]).sort_index(kind="stable")
    prices.attrs = attrs
    state = {"selections": {"swing": {"stale": True}}}
    monkeypatch.setattr(cli, "_state", lambda: state)
    monkeypatch.setattr(cli, "_inputs", lambda state: prices)
    monkeypatch.setattr(cli, "walk_forward", lambda *args, **kwargs: [object()])
    monkeypatch.setattr(cli, "select", lambda results: Pick(FAMILY, "swing", PARAMS, median_fold_net_sharpe=median))
    assert cli.main(["research", "run", "--mode", "swing", "--strategy", FAMILY, "--index-symbol", INDEX]) == 0
    assert "holdout stays sealed" in capsys.readouterr().out
    assert not state["selections"] and "lock_path" not in state
    assert not list(tmp_path.glob("locks/*"))
