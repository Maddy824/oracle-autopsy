"""Pre-registration contracts on invented prices; never reads real market data."""

import json

import numpy as np
import pandas as pd
import pytest

from autopsy import cli, verdict as verdict_module
from autopsy.checks.ledger_check import check_ledger
from autopsy.checks.lookahead import check_lookahead
from autopsy.costs import load_rates, trade_costs
from autopsy.data.schedule import with_schedule
from autopsy.engine import Rebalance, Signal, _prepare_prices, _run_prepared, run_backtest
from autopsy.research.lock import hash_prices
from autopsy.research.trials import TrialLog
from autopsy.research.walkforward import FoldResult, Pick, slippage_grid_for, walk_forward
from autopsy.stats import MinTradesError, _MonthlyPortfolio, _round_trips, random_portfolio_baseline
from autopsy.strategies import REGISTRY
from autopsy.strategies import monthly_momentum as momentum
from test_verdict import seal

FAMILY = "monthly_momentum"
PARAMS = {"variant": "M12"}
INDEX = "NSE:NIFTY 50"


def market(count=330, symbols=8, start="2022-01-03", close=None):
    times = pd.bdate_range(start, periods=count, tz="Asia/Kolkata")
    if close is None:
        close = np.full((count, symbols), 100.)
    frames = []
    for i in range(symbols):
        closing = close[:, i]
        opening = np.r_[closing[0], closing[:-1]]
        frames.append(pd.DataFrame({"symbol": f"S{i:03}", "open": opening, "close": closing,
            "high": np.maximum(opening, closing) * 1.01, "low": np.minimum(opening, closing) * .99,
            "volume": 1000.}, index=times))
    prices = with_schedule(pd.concat(frames).sort_index(kind="stable"), "D")
    prices.attrs.update(index_symbol=INDEX, index_prices=json.dumps([[t.isoformat(), 100 + i / 10]
                                                                  for i, t in enumerate(times)]))
    return prices, times


def orders(prices, variant="M12"):
    params = {"variant": variant}
    return momentum.signals(prices, momentum.features(prices, params), params)


def simulate(prices, variant="M12", slippage=20):
    return run_backtest(prices, orders(prices, variant), "swing", slippage_bps=slippage,
                        rates=load_rates("zerodha"))


@pytest.mark.parametrize("variant", momentum.VARIANTS)
def test_prefix_invariance(variant):
    rng = np.random.default_rng(5)
    prices, times = market(close=100 * np.exp(np.cumsum(rng.normal(.001, .01, (330, 8)), axis=0)))
    full = momentum.features(prices, {"variant": variant})
    assert check_lookahead(lambda p: momentum.features(p, {"variant": variant}), prices, cutoffs=12).verdict == "PASS"
    record = simulate(prices, variant)
    for cutoff in (251, 252, 260, 282, 310):
        prefix = prices.loc[prices.index <= times[cutoff]]
        pd.testing.assert_frame_equal(momentum.features(prefix, {"variant": variant}), full.loc[full.index <= times[cutoff]])
        # A terminal session cannot be declared a month end without its successor.
        assert orders(prefix, variant) == [s for s in orders(prices, variant) if s.time < times[cutoff]]
        assert simulate(prefix, variant).fills == [f for f in record.fills if f.time <= times[cutoff]]


def test_top100_traded_value_not_score_and_symbol_ties():
    prices, times = market(symbols=103)
    prices.loc[prices.symbol == "S102", "volume"] = 2000
    # Median resists a single huge observation.
    prices.loc[(prices.symbol == "S101") & (prices.index == times[260]), "volume"] = 1e12
    features = momentum.features(prices, PARAMS)
    ready = features.loc[features.index == times[260]]
    assert set(ready.loc[ready.universe, "symbol"]) == {f"S{i:03}" for i in range(99)} | {"S102"}
    assert not features.loc[features.index < times[252], "history_eligible"].any()
    assert features.loc[features.index == times[252], "history_eligible"].all()
    assert next(s for s in orders(prices) if s.symbols).symbols == tuple(f"S{i:03}" for i in range(5))


@pytest.mark.parametrize("column,value", [("open", 0), ("high", -1), ("low", np.nan),
                                          ("close", 0), ("volume", 0), ("volume", np.inf)])
def test_253_consecutive_positive_finite_bars(column, value):
    prices, times = market(symbols=2)
    prices.loc[(prices.symbol == "S000") & (prices.index == times[5]), column] = value
    prices = prices.loc[~((prices.symbol == "S001") & (prices.index == times[8]))]
    features = momentum.features(prices, PARAMS)
    for symbol, ready in (("S000", 258), ("S001", 261)):
        rows = features.loc[features.symbol == symbol]
        assert not rows.loc[rows.index < times[ready], "history_eligible"].any()
        assert rows.loc[times[ready], "history_eligible"]


def test_index_excluded_and_late_listing_waits_253_sessions():
    prices, times = market(symbols=3)
    prices.loc[prices.symbol == "S000", "symbol"] = INDEX
    prices = prices.loc[~((prices.symbol == "S001") & (prices.index < times[20]))]
    features = momentum.features(prices, PARAMS)
    assert not features.loc[features.symbol == INDEX, "universe"].any()
    stock = features.loc[features.symbol == "S001"]
    assert not stock.loc[:times[271], "universe"].any()
    assert stock.loc[times[272], "universe"]


def test_month_end_uses_index_holidays_and_never_final_session():
    prices, times = market(start="2023-01-02", count=70)
    holiday = pd.Timestamp("2023-01-31", tz="Asia/Kolkata")
    prices = prices.loc[prices.index != holiday]
    prices.attrs["index_prices"] = json.dumps([[t.isoformat(), 100.] for t in times if t != holiday])
    expected = pd.DatetimeIndex(["2023-01-30", "2023-02-28", "2023-03-31"], tz="Asia/Kolkata")
    assert momentum.rebalance_days(prices).equals(expected)
    prefix = prices.loc[prices.index <= expected[-1]]
    assert momentum.rebalance_days(prefix).equals(expected[:-1])


def test_m12_and_m12v_exact_scores_and_distinct_ranking():
    rng = np.random.default_rng(13)
    log_returns = rng.normal(size=(330, 8)) * np.linspace(.002, .03, 8) + .001
    close = 100 * np.exp(np.cumsum(log_returns, axis=0))
    prices, times = market(close=close)
    raw = momentum.features(prices, PARAMS)
    scaled = momentum.features(prices, {"variant": "M12V"})
    for i in range(8):
        expected = close[279, i] / close[48, i] - 1
        deviation = np.std(np.diff(np.log(close[48:301, i])), ddof=1)
        row = raw.loc[(raw.index == times[300]) & (raw.symbol == f"S{i:03}")].iloc[0]
        vrow = scaled.loc[(scaled.index == times[300]) & (scaled.symbol == f"S{i:03}")].iloc[0]
        assert row.score == pytest.approx(expected)
        assert vrow.volatility == pytest.approx(deviation)
        assert vrow.score == pytest.approx(expected / deviation)
    assert orders(prices)[-1].symbols != orders(prices, "M12V")[-1].symbols


def test_amendment_1a_exact_filter_and_attached_candidates():
    names = ["ordinary", "an ETF", "BEES trust", "INAV", "x NAV", "AMC - growth", "some fund",
             "REIT", "InvIT", "Bharat Bond", "ordinary", "ordinary", "ordinary", "ordinary", "ordinary"]
    symbols = ["KEEP", "A", "B", "C", "D", "E", "F", "G", "H", "I", "X-BE", "XBEES", "XIETF", "XETF", "XINAV"]
    instruments = pd.DataFrame({"name": names, "tradingsymbol": symbols, "segment": "NSE", "instrument_type": "EQ"})
    instruments = pd.concat([instruments, pd.DataFrame([
        {"name": "ordinary", "tradingsymbol": "FUT", "segment": "NFO", "instrument_type": "EQ"},
        {"name": "ordinary", "tradingsymbol": "OPT", "segment": "NSE", "instrument_type": "CE"}])])
    assert momentum.candidate_symbols(instruments) == ("NSE:KEEP",)
    prices, _ = market(symbols=2)
    prices["symbol"] = prices.symbol.map({"S000": "NSE:KEEP", "S001": "NSE:A"})
    prices = momentum.attach_candidates(prices, instruments)
    features = momentum.features(prices, PARAMS)
    assert set(features.loc[features.universe, "symbol"]) == {"NSE:KEEP"}


def target(time, symbols, universe=tuple(f"S{i:03}" for i in range(8))):
    return Rebalance(time, tuple(symbols), universe)


def test_d1_sells_d2_buys_held_targets_never_resize_or_exit_at_end():
    prices, times = market(count=65)
    signals = [target(times[0], [f"S{i:03}" for i in range(5)]),
               target(times[20], [f"S{i:03}" for i in range(1, 6)]),
               target(times[40], [f"S{i:03}" for i in range(1, 6)])]
    record = run_backtest(prices, signals, "swing", slippage_bps=10, rates=load_rates("zerodha"))
    assert [(f.time, f.symbol, f.side) for f in record.fills] == (
        [(times[2], f"S{i:03}", "BUY") for i in range(5)]
        + [(times[21], "S000", "SELL"), (times[22], "S005", "BUY")])
    assert check_ledger(record).verdict == "PASS"


def test_fee_inclusive_20_percent_of_open_equity_after_gap():
    prices, times = market(count=10)
    prices.loc[(prices.symbol == "S000") & (prices.index >= times[5]), ["open", "high", "low", "close"]] = 1000.
    signals = [target(times[0], ["S000"]), target(times[3], ["S000", "S001"])]
    rates = load_rates("zerodha")
    record = run_backtest(prices, signals, "swing", slippage_bps=10, rates=rates)
    first, second = record.fills
    cash = record.start_cash - first.qty * first.price - first.fee
    cap = .2 * (cash + first.qty * 1000)
    assert second.time == times[5]
    assert second.qty * second.price + second.fee <= cap
    assert (second.qty + 1) * second.price + trade_costs("BUY", (second.qty + 1) * second.price,
                                                       "delivery_equity", rates).total > cap
    assert second.qty * second.price > .2 * record.start_cash


def test_settled_cash_rejection_expires_and_whole_shares():
    prices, times = market(count=8)
    # Spend essentially all cash, liquidate five names on day 3, then attempt
    # an unaffordable same-open entry. Day 4 settlement must not revive it.
    prices.loc[prices.symbol == "S005", ["open", "high", "low", "close"]] = 1000.
    signals = [Signal(times[0], f"S{i:03}", 1, equity_fraction=.2) for i in range(5)]
    signals += [Signal(times[2], f"S{i:03}", 0) for i in range(5)]
    signals += [Signal(times[2], "S005", 1, equity_fraction=.2)]
    record = run_backtest(prices, signals, "swing", slippage_bps=10, rates=load_rates("zerodha"))
    assert len(record.fills) == 10
    assert all(f.symbol != "S005" for f in record.fills)
    retry = run_backtest(prices, signals + [Signal(times[3], "S005", 1, equity_fraction=.2)],
                         "swing", slippage_bps=10, rates=load_rates("zerodha"))
    assert retry.fills[-1].time == times[4] and retry.fills[-1].symbol == "S005"


def test_missing_execution_bar_expires_not_next_available_stock_bar():
    prices, times = market(count=10)
    prices = prices.loc[~((prices.symbol == "S000") & (prices.index == times[2]))]
    record = run_backtest(prices, [target(times[0], ["S000"])], "swing",
                          slippage_bps=10, rates=load_rates("zerodha"))
    assert not record.fills


def test_restriction_before_engine_does_not_change_fills_or_equity():
    prices, _ = market(symbols=105)
    signals = orders(prices)
    restricted = simulate(prices)
    # Explicit unfiltered engine path is the counterfactual.
    fills, equity = _run_prepared(_prepare_prices(prices, "swing"), signals, "swing",
                                  slippage_bps=20, rates=load_rates("zerodha"))
    assert restricted.fills == fills
    pd.testing.assert_series_equal(restricted.reported_equity, equity, check_exact=True)
    plan = _MonthlyPortfolio(restricted, PARAMS)
    assert plan.prepared.prices.symbol.nunique() == 100
    assert not set(plan.prepared.prices.symbol) & {f"S{i:03}" for i in range(100, 105)}


def test_random_replay_seed_and_replacement_counts():
    prices = edge_market(True, count=900)
    record = simulate(prices)
    plan = _MonthlyPortfolio(record, PARAMS)
    fills, equity = plan.run(plan.strategy_signals)
    assert fills == record.fills
    pd.testing.assert_series_equal(equity, record.reported_equity, check_exact=True)
    rng = np.random.default_rng(9)
    for _ in range(3):
        selector = plan.draw(rng)
        def checked(rebalance, held):
            sells, buys = selector(rebalance, held)
            assert len(sells) == plan.counts[rebalance.time][0]
            assert len(buys) == plan.counts[rebalance.time][1]
            assert not set(buys) & set(held)
            assert set(buys) <= set(rebalance.universe)
            return sells, buys
        _, equity = plan.run(checked)
        assert equity.attrs["autopsy_replacements"] == record.reported_equity.attrs["autopsy_replacements"]
    actual = random_portfolio_baseline(record, PARAMS, runs=5, seed=9, family=FAMILY)
    np.testing.assert_array_equal(actual, random_portfolio_baseline(record, PARAMS, runs=5, seed=9, family=FAMILY))
    record.reported_equity.iloc[-1] += 1
    with pytest.raises(ValueError, match="replay does not match"):
        _MonthlyPortfolio(record, PARAMS)


def edge_market(edge, count=1900):
    symbols = 20
    if edge:
        phase = np.arange(count)[:, None] * (2 * np.pi / 900) + np.arange(symbols) * (2 * np.pi / symbols)
        close = 100 * np.exp(.7 * np.sin(phase))
    else:
        rng = np.random.default_rng(0)
        close = 100 * np.exp(np.cumsum(rng.normal(0, .015, (count, symbols)), axis=0))
    return market(count=count, symbols=symbols, close=close)[0]


@pytest.mark.parametrize("edge", [True, False])
def test_planted_momentum_passes_random_gate_no_edge_fails(tmp_path, monkeypatch, edge):
    prices = edge_market(edge)
    record = simulate(prices)
    assert len(_round_trips(record)) >= 30
    calls = []
    def small_baseline(record, params, runs, seed, *, family):
        calls.append((runs, seed, family))
        return random_portfolio_baseline(record, params, runs=39, seed=seed, family=family)
    monkeypatch.setattr(verdict_module, "random_portfolio_baseline", small_baseline)
    monkeypatch.setattr(verdict_module, "random_entry_baseline", lambda *a, **k: pytest.fail("legacy sampler"))
    pick = Pick(FAMILY, "swing", PARAMS)
    result = verdict_module.decide(pick, record, [], seal(tmp_path, pick, prices))
    assert calls == [(1000, 0, FAMILY)]
    checks = {c.name: c.verdict for c in result.checks}
    assert checks["random_portfolio"] == "PASS", result
    assert checks["random_entry"] == ("PASS" if edge else "FAIL"), result
    assert "delisted" in result.stats["survivorship_bias"]
    assert result.stats["nifty50_buy_and_hold"] is not None


def test_fewer_than_30_trades_cant_tell_without_forced_exits(tmp_path):
    prices, _ = market()
    record = simulate(prices)
    assert len(record.fills) == 5 and all(f.side == "BUY" for f in record.fills)
    pick = Pick(FAMILY, "swing", PARAMS)
    result = verdict_module.decide(pick, record, [], seal(tmp_path, pick, prices))
    assert next(c for c in result.checks if c.name == "trades").verdict == "CAN'T TELL"
    assert result.verdict == "NO-GO"


@pytest.mark.parametrize("variant", momentum.VARIANTS)
def test_warmup_matches_full_history_and_is_hashed(variant):
    params = {"variant": variant}
    prices = edge_market(True, count=800)
    start = prices.index.unique()[400]
    window = momentum.with_warmup(prices.loc[prices.index >= start], prices.loc[prices.index < start])
    full = momentum.features(prices, params)
    pd.testing.assert_frame_equal(momentum.features(window, params), full.loc[full.index >= start], rtol=1e-10, atol=1e-10)
    signals = [s for s in orders(prices, variant) if s.time >= start]
    record = run_backtest(window, signals, "swing", slippage_bps=20, rates=load_rates("zerodha"))
    assert _MonthlyPortfolio(record, params).run(orders(window, variant))[0] == record.fills
    changed = window.copy()
    del changed.attrs["monthly_warmup"]
    assert hash_prices(window) != hash_prices(changed)


def test_rejected_monthly_entry_expires_and_rank_order_is_preserved():
    prices, times = market(count=40)
    prices.loc[(prices.symbol == "S005") & (prices.index == times[2]), "open"] = 1e9
    signals = [target(times[0], ["S005", "S004", "S003"]),
               target(times[20], ["S005", "S004", "S003"])]
    record = run_backtest(prices, signals, "swing", slippage_bps=20, rates=load_rates("zerodha"))
    assert [(f.time, f.symbol) for f in record.fills] == [(times[2], "S004"), (times[2], "S003"), (times[22], "S005")]


def test_benchmark_same_window_first_open_and_report(tmp_path):
    from autopsy.report import render_report
    prices, times = market()
    prices.attrs["monthly_index_opens"] = json.dumps([[t.isoformat(), 90.] for t in times])
    context = momentum.benchmark(prices, times[280], times[300])
    assert context["net_profit"] == pytest.approx(200_000 * (129.9 / 90 - 1))
    record = simulate(prices)
    pick = Pick(FAMILY, "swing", PARAMS)
    verdict = verdict_module.decide(pick, record, [], seal(tmp_path, pick, prices))
    path = render_report([verdict], [record], [], tmp_path / "report.html")
    report = path.read_text()
    assert "Nifty 50 buy-and-hold (context only)" in report
    assert "Companies delisted or merged" in report


def test_default_baseline_runs_1000_and_seed_zero():
    prices, _ = market(count=40, symbols=2)
    record = simulate(prices)
    baseline = random_portfolio_baseline(record, PARAMS, family=FAMILY)
    assert baseline.shape == (1000,)
    np.testing.assert_array_equal(baseline, np.zeros(1000))


def test_registry_folds_two_trials_warmup_and_nifty_context(tmp_path):
    strategy = REGISTRY[FAMILY]
    assert strategy.mode == "swing" and dict(strategy.params_grid) == {"variant": ("M12", "M12V")}
    assert slippage_grid_for(strategy) == (10,)
    prices, times = market(start="2014-01-01", count=650)
    log = TrialLog(tmp_path / "trials.jsonl")
    results = walk_forward(strategy, prices, times[-1], trial_log=log)
    assert len(results) == 8 and log.trial_count == 2
    assert all(row.start >= pd.Timestamp("2015-01-01", tz="Asia/Kolkata") for row in results)
    assert all(row.slippage_bps == 20 and row.nifty50_buy_and_hold is not None for row in results)
    assert all(row.verdict == "CAN'T TELL" for row in results)
    with pytest.raises(ValueError, match="slippage grid"):
        walk_forward(strategy, prices, times[-1], trial_log=log, slippage_grid=(5,))


def test_cli_requires_index_before_trials(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPSY_DATA_DIR", str(tmp_path))
    prices, _ = market()
    monkeypatch.setattr(cli, "_state", lambda: {})
    monkeypatch.setattr(cli, "_inputs", lambda state: prices)
    assert cli.main(["research", "run", "--mode", "swing", "--strategy", FAMILY]) == 2
    assert "requires --index-symbol" in capsys.readouterr().err
    assert TrialLog().trial_count == 0


@pytest.mark.parametrize("median", [0., -.1])
def test_cli_nonpositive_development_seals_holdout(tmp_path, monkeypatch, capsys, median):
    monkeypatch.setenv("AUTOPSY_DATA_DIR", str(tmp_path))
    prices, _ = market(count=400, start="2024-01-01")
    index = prices.loc[prices.symbol == "S000"].copy()
    index["symbol"] = INDEX
    attrs = prices.attrs.copy()
    prices = pd.concat([prices, index]).sort_index(kind="stable")
    prices.attrs = attrs
    prices.attrs["monthly_candidates"] = json.dumps(sorted(prices.symbol.unique()))
    state = {"selections": {"swing": {"stale": True}}}
    monkeypatch.setattr(cli, "_state", lambda: state)
    monkeypatch.setattr(cli, "_inputs", lambda state: prices)
    monkeypatch.setattr(cli, "walk_forward", lambda *a, **k: [])
    # Supply a result without a benchmark; selection remains separately controlled.
    row = FoldResult(FAMILY, "swing", PARAMS, 10, 0, prices.index.min(), prices.index.max(), median, 0., "PASS", "", 4)
    monkeypatch.setattr(cli, "walk_forward", lambda *a, **k: [row])
    monkeypatch.setattr(cli, "select", lambda results: Pick(FAMILY, "swing", PARAMS, median_fold_net_sharpe=median))
    assert cli.main(["research", "run", "--mode", "swing", "--strategy", FAMILY, "--index-symbol", INDEX]) == 0
    assert "holdout stays sealed" in capsys.readouterr().out
    assert not state["selections"] and not list(tmp_path.glob("locks/*"))
