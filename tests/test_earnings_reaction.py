"""Invented daily prices/events only; no services or network access."""

from dataclasses import replace
import json
from math import floor
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from autopsy import cli
from autopsy.checks.ledger_check import check_ledger
from autopsy.checks.lookahead import check_lookahead
from autopsy.costs import load_rates
from autopsy.data.schedule import with_schedule
from autopsy.data.store import load_snapshot, save_snapshot
from autopsy.engine import Signal, run_backtest
from autopsy.news.events import Event, EventLedger, with_events
from autopsy.research.lock import hash_prices
from autopsy.research.trials import TrialLog
from autopsy.research.walkforward import walk_forward
from autopsy.stats import random_entry_baseline
from autopsy.strategies import REGISTRY
from autopsy.strategies import earnings_reaction as reaction

INDEX = "NSE:NIFTY 50"
PARAMS = {"variant": "h10_regime"}


def market(count=260, symbols=("ALPHA",), day=205, midnight=False):
    times = pd.bdate_range("2023-01-02", periods=count, tz="Asia/Kolkata")
    if not midnight:
        times += pd.Timedelta(hours=9, minutes=15)
    frames = []
    for i, symbol in enumerate((*symbols, INDEX)):
        if symbol == INDEX:
            close = 100 + np.arange(count) * .1
            opens = close.copy()
        else:
            close = np.where(np.arange(count) >= day, 105. + i, 100.)
            opens = np.r_[close[0], close[:-1]]
        frames.append(pd.DataFrame({"symbol": symbol, "open": opens, "close": close,
                                    "high": np.maximum(opens, close) + 1,
                                    "low": np.minimum(opens, close) - 1, "volume": 1000}, index=times))
    prices = with_schedule(pd.concat(frames).sort_index(kind="stable"), "D")
    events = [notice(symbol, times[day].normalize() - pd.Timedelta(hours=7)) for symbol in symbols]
    return with_events(prices, events), times


def notice(symbol, time):
    return Event("", symbol, "results", "NSE", time,
                 pd.Timestamp("2026-01-01", tz="Asia/Kolkata"), "invented", 0)


def prepared(**kwargs):
    prices, times = market(**kwargs)
    return reaction.attach_index(prices, INDEX), times


def simulate(prices, variant="h10_regime", slippage=10):
    params = {"variant": variant}
    features = reaction.features(prices, params)
    signals = reaction.signals(prices, features, params)
    return run_backtest(prices, signals, "swing", slippage_bps=slippage, rates=load_rates("zerodha"))


def test_reaction_regime_and_simple_atr_math():
    prices, times = prepared()
    feature = reaction.features(prices, PARAMS).loc[times[205]]
    assert feature.excess == pytest.approx(105 / 100 - 120.5 / 120.4)
    assert feature.atr20 == pytest.approx((19 * 2 + 7) / 20)
    assert feature.reaction and feature.regime and feature.eligible
    # Exact equality to the SMA fails the strict regime comparison.
    rows = json.loads(prices.attrs["index_prices"])
    prices.attrs["index_prices"] = json.dumps([[t, 100.] for t, _ in rows])
    assert not reaction.features(prices, PARAMS).loc[times[205]].eligible
    assert reaction.features(prices, {"variant": "h10_noregime"}).loc[times[205]].eligible


@pytest.mark.parametrize("stock,index_close,qualifies", [(100, 100, False), (99, 90, False),
                                                          (105, 106, False), (105, 105, False),
                                                          (105, 104, True)])
def test_reaction_strict_up_and_excess(stock, index_close, qualifies):
    prices, times = prepared()
    prices.loc[times[205], "close"] = stock
    rows = json.loads(prices.attrs["index_prices"])
    prices.attrs["index_prices"] = json.dumps([[t, index_close if i == 205 else 100]
                                              for i, (t, _) in enumerate(rows)])
    features = reaction.features(prices, {"variant": "h10_noregime"})
    assert bool(features.loc[times[205]].eligible) == qualifies


def test_insufficient_200_sessions_blocks_regime_only():
    prices, times = prepared(count=100, day=50)
    assert not reaction.features(prices, PARAMS).loc[times[50]].eligible
    assert reaction.features(prices, {"variant": "h10_noregime"}).loc[times[50]].eligible


@pytest.mark.parametrize("midnight", [False, True])
@pytest.mark.parametrize("clock,offset", [("08:59:00", 0), ("09:15:00", 1), ("16:30:00", 1)])
def test_dissemination_strictly_before_session_open(midnight, clock, offset):
    prices, times = prepared(midnight=midnight)
    timestamp = times[204].normalize() + pd.Timedelta(clock)
    prices = with_events(prices, [notice("ALPHA", timestamp)])
    assert reaction.event_sessions(prices) == {("ALPHA", times[204 + offset].normalize())}


def test_schedule_missing_d_does_not_postpone_event():
    prices, times = prepared()
    prices = prices.loc[prices.index != times[205]].copy()  # retains expected D
    assert reaction.event_sessions(prices) == {("ALPHA", times[205].normalize())}
    assert not reaction.features(prices, PARAMS).eligible.any()


def test_prefix_lookahead_and_signal_stability():
    prices, times = prepared(symbols=("ALPHA", "BETA"))
    assert check_lookahead(lambda p: reaction.features(p, PARAMS), prices, cutoffs=30).verdict == "PASS"
    prefix = prices.loc[prices.index <= times[205]].copy()
    expected = reaction.signals(prefix, reaction.features(prefix, PARAMS), PARAMS)
    actual = reaction.signals(prices, reaction.features(prices, PARAMS), PARAMS)
    assert expected == [s for s in actual if s.time <= times[205]]
    full = simulate(prices)
    truncated = simulate(prices.loc[prices.index <= times[210]])
    assert truncated.fills == [fill for fill in full.fills if fill.time <= times[210]]


def test_entry_fill_risk_sizing_and_close_stop_next_open():
    prices, times = prepared()
    distance = 2 * reaction.features(prices, PARAMS).loc[times[205]].atr20
    # Gap entry makes the actual fill-based stop materially different from D close.
    prices.loc[times[206], ["open", "high", "close"]] = [120, 121, 120]
    prices.loc[times[207], "close"] = 114
    prices.loc[times[208], "open"] = 111
    prices.loc[times[208], "high"] = 112
    record = simulate(prices)
    entry, exit = record.fills
    assert entry.time == times[206] and entry.price == pytest.approx(120 * 1.001)
    assert entry.qty == floor(min(.2 * 200_000 / entry.price, .0025 * 200_000 / distance))
    assert exit.time == times[208] and exit.price == pytest.approx(111 * .999)
    assert check_ledger(record).verdict == "PASS"


def test_stop_is_strict_and_entry_session_close_can_trigger_it():
    prices, times = prepared()
    distance = 2 * reaction.features(prices, PARAMS).loc[times[205]].atr20
    prices.loc[times[206], "close"] = 105 - distance
    assert simulate(prices, slippage=0).fills[1].time == times[217]
    prices.loc[times[206], "close"] -= .01
    assert simulate(prices, slippage=0).fills[1].time == times[207]


def test_managed_sizing_uses_open_equity_and_notional_cap():
    prices, times = prepared(count=10, symbols=("A", "B"), day=5)
    prices.loc[(prices.symbol == "A") & (prices.index == times[2]), "open"] = 200
    signals = [Signal(times[0], "A", 1, risk_distance=.1, holding_sessions=5),
               Signal(times[1], "B", 1, risk_distance=.1, holding_sessions=5)]
    record = run_backtest(prices, signals, "swing", slippage_bps=0, rates=load_rates("zerodha"))
    a, b = record.fills[:2]
    assert a.qty == 400
    equity_at_b_open = 200_000 - a.qty * a.price - a.fee + a.qty * 200
    assert b.qty == floor(.2 * equity_at_b_open / b.price) > 400
    # Poison B's entry-day close: its fill cannot change retroactively.
    prices.loc[(prices.symbol == "B") & (prices.index == times[2]), "close"] = 10_000
    changed = run_backtest(prices, signals, "swing", slippage_bps=0, rates=load_rates("zerodha"))
    assert changed.fills[:2] == record.fills[:2]


def test_risk_sizing_still_respects_cash_and_fees():
    prices, times = prepared(count=10, day=5)
    record = run_backtest(prices, [Signal(times[0], "ALPHA", 1, risk_distance=4, holding_sessions=5)],
                          "swing", capital=100, slippage_bps=10, rates=load_rates("zerodha"))
    assert not record.fills  # risk budget cannot fund a whole share


@pytest.mark.parametrize("variant,hold", [("h10_regime", 10), ("h5_regime", 5),
                                          ("h20_regime", 20), ("h10_noregime", 10)])
def test_hold_matches_holding_signals(variant, hold):
    prices, times = prepared()
    record = simulate(prices, variant)
    assert [fill.time for fill in record.fills] == [times[206], times[207 + hold]]


def test_five_position_cap_rank_excess_then_symbol_and_index_exclusion():
    symbols = ("A", "B", "C", "D", "E", "F", "G")
    prices, times = prepared(symbols=symbols)
    # B, C and D tie for the two remaining slots; D loses by symbol.
    prices.loc[prices.symbol.isin(["B", "D"]) & (prices.index >= times[205]), "close"] = 107.
    features = reaction.features(prices, PARAMS)
    signals = reaction.signals(prices, features, PARAMS)
    record = run_backtest(prices, reversed(signals), "swing", slippage_bps=10, rates=load_rates("zerodha"))
    buys = [fill for fill in record.fills if fill.side == "BUY"]
    assert [fill.symbol for fill in buys] == ["G", "F", "E", "B", "C"]
    assert len(buys) == 5 and INDEX not in set(record.prices.symbol)
    # A later event in a rejected symbol remains actionable after capacity frees.
    later = Signal(times[230], "A", 1, risk_distance=4, holding_sessions=5)
    again = run_backtest(prices, [*signals, later], "swing", slippage_bps=10, rates=load_rates("zerodha"))
    assert any(fill.symbol == "A" and fill.time == times[231] for fill in again.fills)


def test_four_registered_trials_and_context_survives_walkforward(tmp_path):
    strategy = REGISTRY["earnings_reaction"]
    assert dict(strategy.params_grid) == {"variant": tuple(reaction.VARIANTS)}
    prices, times = prepared()
    log = TrialLog(tmp_path / "trials.jsonl")
    results = walk_forward(strategy, prices, times[-1] + pd.Timedelta(days=1), folds=1, trial_log=log)
    assert log.trial_count == len(results) == 4
    assert {row.base_slippage_bps for row in results} == {10}
    assert all(row["metrics"]["folds"][0]["data_check"] == {} for row in log.rows()
               if row["metrics"]["status"] == "complete")
    with pytest.raises(ValueError, match="slippage grid"):
        walk_forward(strategy, prices, times[-1], trial_log=log, slippage_grid=(5, 10, 25))


@pytest.mark.parametrize("kind", ["absent", "empty", "untimed", "board", "unknown", "future", "no_index"])
def test_missing_required_data_refuses(kind):
    prices, times = prepared()
    event = notice("ALPHA", times[204])
    if kind == "absent":
        del prices.attrs["events"]
    elif kind == "empty":
        prices = with_events(prices, [])
    elif kind == "no_index":
        del prices.attrs["index_symbol"]
    else:
        changes = {"untimed": {"disseminated_at": None}, "board": {"kind": "board_meeting"},
                   "unknown": {"symbol": "MISSING"}, "future": {"disseminated_at": times[-1] + pd.Timedelta(days=10)}}
        prices = with_events(prices, [replace(event, **changes[kind])])
    assert reaction.data_check(prices).verdict == "CAN'T TELL"


def test_nse_bare_export_symbol_matches_kite_equity():
    prices, times = prepared(symbols=("NSE:ALPHA",))
    prices = with_events(prices, [notice("ALPHA", times[204])])
    assert reaction.event_sessions(prices) == {("NSE:ALPHA", times[205].normalize())}


def test_index_context_snapshot_hash_and_past_warmup(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPSY_DATA_DIR", str(tmp_path))
    prices, times = prepared()
    window = prices.loc[prices.index >= times[200]].copy()
    path = save_snapshot(window, "raw", "invented")
    restored, _ = load_snapshot(path)
    assert hash_prices(restored) == hash_prices(window)
    assert reaction.features(restored, PARAMS).regime.all()
    restored.attrs["index_symbol"] = "another index"
    assert hash_prices(restored) != hash_prices(window)
    restored.attrs["index_symbol"] = INDEX
    restored.attrs["index_prices"] = "[]"
    assert hash_prices(restored) != hash_prices(window)


@pytest.mark.parametrize("events_present", [True, False])
def test_cli_filters_to_exactly_four_trials_and_excludes_index(tmp_path, monkeypatch, capsys, events_present):
    monkeypatch.setenv("AUTOPSY_DATA_DIR", str(tmp_path))
    prices, _ = market(count=600)
    events = reaction.events_from_prices(prices)
    prices.attrs.pop("events")
    if events_present:
        for event in events:
            EventLedger().add(event)
    monkeypatch.setattr(cli, "_state", lambda: {"source": "invented"})
    monkeypatch.setattr(cli, "_inputs", lambda state: prices)
    code = cli.main(["research", "run", "--mode", "swing", "--strategy", "earnings_reaction",
                     "--index-symbol", INDEX])
    assert code == 0
    log = TrialLog()
    assert log.trial_count == 4
    assert {row["strategy"] for row in log.rows()} == {"earnings_reaction"}
    assert {row["params"]["variant"] for row in log.rows()} == set(reaction.VARIANTS)
    state = json.loads((tmp_path / "session.json").read_text())
    preview = json.loads(Path(state["preview_path"]).read_text())
    frozen, _ = load_snapshot(preview["snapshot"])
    assert INDEX not in set(frozen.symbol) and frozen.attrs["index_symbol"] == INDEX
    if not events_present:
        assert "no results events" in capsys.readouterr().err


def test_cli_requires_index_and_matching_mode(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPSY_DATA_DIR", str(tmp_path))
    prices, _ = market()
    monkeypatch.setattr(cli, "_state", lambda: {})
    monkeypatch.setattr(cli, "_inputs", lambda state: prices)
    assert cli.main(["research", "run", "--mode", "swing", "--strategy", "earnings_reaction"]) == 2
    assert "requires --index-symbol" in capsys.readouterr().err
    assert cli.main(["research", "run", "--mode", "intraday", "--strategy", "earnings_reaction"]) == 2
    assert TrialLog().trial_count == 0


def test_cli_index_also_benchmark_and_other_family_filter(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPSY_DATA_DIR", str(tmp_path))
    prices, _ = market(count=600)
    monkeypatch.setattr(cli, "_state", lambda: {"source": "invented"})
    monkeypatch.setattr(cli, "_inputs", lambda state: prices)
    assert cli.main(["research", "run", "--mode", "swing", "--strategy", "nday_breakout",
                     "--index-symbol", INDEX, "--benchmark-symbol", INDEX]) == 0
    assert {row["strategy"] for row in TrialLog().rows()} == {"nday_breakout"}
    assert TrialLog().trial_count == 6  # default parameter/slippage grid unchanged
    state = json.loads((tmp_path / "session.json").read_text())
    preview = json.loads(Path(state["preview_path"]).read_text())
    frozen, _ = load_snapshot(preview["snapshot"])
    assert INDEX not in set(frozen.symbol)


def test_unmatched_random_portfolio_cannot_satisfy_preregistered_gate(tmp_path):
    from test_verdict import seal
    from autopsy.research.walkforward import Pick
    from autopsy.verdict import decide
    prices, _ = prepared()
    pick = Pick("earnings_reaction", "swing", PARAMS)
    record = simulate(prices, slippage=20)
    verdict = decide(pick, record, [], seal(tmp_path, pick, prices))
    check = next(check for check in verdict.checks if check.name == "random_portfolio")
    assert check.verdict == "CAN'T TELL" and verdict.verdict == "NO-GO"
    assert "five-position" in check.evidence["reason"]


def test_season_matched_baseline_samples_only_next_open():
    from test_stats import baseline_fixture
    record, _ = baseline_fixture("swing")
    day = record.prices.index.unique()[10].normalize()
    # A single allowed signal day makes every sampled entry/exit deterministic,
    # retaining each actual symbol/quantity and one-bar realized hold.
    baseline = random_entry_baseline(record, record.prices, runs=8, eligible_signal_days={day})
    assert len(set(baseline)) == 1
    # Use actual next observed sessions (weekday fixture may cross a weekend).
    times = record.prices.index.unique()
    start = times.get_loc(times[times.normalize() == day][0])
    modified = record.prices.copy()
    modified.loc[~modified.index.isin(times[start + 1:start + 3]), "open"] *= 5
    np.testing.assert_array_equal(baseline, random_entry_baseline(
        record, modified, runs=8, eligible_signal_days={day}))
    with pytest.raises(ValueError, match="no tradable entries"):
        random_entry_baseline(record, record.prices, runs=1, eligible_signal_days=set())
