from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from autopsy.costs import load_rates
from autopsy.checks.lookahead import check_lookahead
from autopsy.data.schedule import with_schedule
from autopsy.engine import Signal, run_backtest
from autopsy.news.events import Event, EventLedger, with_events
from autopsy.news.nse_filings import load_nse_announcements, load_nse_deals
from autopsy.strategies import REGISTRY, Strategy, registry_hash
from autopsy.strategies.events import results_day_filter
from autopsy.research.lock import hash_prices
from autopsy.research.trials import TrialLog
from autopsy.research.walkforward import walk_forward
from synthetic_bars import five_minute_bars


def ts(value):
    return pd.Timestamp(value, tz="Asia/Kolkata")


def event(**changes):
    values = dict(isin="INE000TEST01", symbol="ALPHA", kind="results", source="NSE",
                  disseminated_at=ts("2025-01-01 10:01"), first_seen_at=ts("2025-01-06 12:00"),
                  doc_hash=hashlib.sha256(b"invented earnings document").hexdigest(), revision=0,
                  earnings_change=10.0, document=b"invented earnings document")
    return Event(**(values | changes))


def bars(days=8, events=()):
    prices = five_minute_bars(days)
    prices[["open", "close"]] = 100.0
    prices["high"], prices["low"] = 101.0, 99.0
    return with_events(with_schedule(prices, "5min"), events)


@pytest.mark.parametrize("delay", [1, 5, 15])
@pytest.mark.parametrize("name", ["earnings_continuation", "post_results_orb", "block_buy_continuation"])
def test_no_entry_before_dissemination(delay, name):
    notice = event(kind="bulk_deal", side="BUY") if name == "block_buy_continuation" else event()
    prices = bars(events=[notice])
    if name == "post_results_orb":
        prices.loc[ts("2025-01-02 09:30"):ts("2025-01-02 15:25"), "close"] = 102.0
        prices.loc[ts("2025-01-02 09:30"):ts("2025-01-02 15:25"), "high"] = 103.0
    strategy = REGISTRY[name]
    params = {"delay": delay, **({"holding_days": 1} if name == "earnings_continuation" else {})}
    signals = strategy.signals(prices, strategy.features(prices, params), params)
    entry = next(s for s in signals if s.target == 1)
    ready = notice.disseminated_at + pd.Timedelta(minutes=delay)
    expected = (prices.index[prices.index >= ready][0] if name == "earnings_continuation"
                else ts("2025-01-02 09:35" if name == "post_results_orb" else "2025-01-02 09:15"))
    assert entry.time == expected
    record = run_backtest(prices, signals, strategy.mode, slippage_bps=10, rates=load_rates("zerodha"))
    assert record.fills[0].time == prices.index[prices.index > expected][0]
    assert record.fills[0].time >= ready


def test_filter_uses_only_prior_notices():
    def features(prices, params):
        return prices[["symbol"]]

    def signals(prices, features, params):
        return [Signal(ts("2025-01-01 09:30"), "ALPHA", 1)]

    strategy = results_day_filter(Strategy("morning", "intraday", {}, features, signals))
    for notice, blocked in [(event(disseminated_at=ts("2025-01-01 10:00")), False),
                            (event(disseminated_at=ts("2025-01-01 09:00")), True),
                            (event(disseminated_at=ts("2025-01-01 09:15")), False),
                            (event(disseminated_at=ts("2024-12-30 10:00"),
                                   kind="board_meeting", scheduled_for=ts("2025-01-01").date()), True)]:
        prices = bars(events=[notice])
        result = strategy.signals(prices, strategy.features(prices, {}), {})
        assert bool(result) is not blocked
    assert strategy.name == "morning+results_filter"
    assert "orb+results_filter" in REGISTRY


def test_dedup_across_exchanges(tmp_path):
    ledger = EventLedger(tmp_path / "events.jsonl")
    original = event()
    assert ledger.add(original)
    assert not ledger.add(replace(original, source="BSE", symbol="500001",
                                  disseminated_at=ts("2025-01-01 10:02")))
    revision = replace(original, doc_hash=hashlib.sha256(b"revised").hexdigest(),
                       document=b"revised", revision=1)
    assert ledger.add(revision)
    assert EventLedger(ledger.path).events() == [original, revision]
    assert ledger.events()[0].document == original.document


@pytest.mark.parametrize("name", ["earnings_continuation", "post_results_orb", "block_buy_continuation",
                                  "orb+results_filter"])
def test_missing_timestamp_cant_tell(name):
    notice = event(disseminated_at=None, kind="bulk_deal" if name == "block_buy_continuation" else "results")
    prices = bars(events=[notice])
    strategy = REGISTRY[name]
    assert strategy.data_check(prices).verdict == "CAN'T TELL"
    # An unrelated strategy is not invalidated by incomplete news.
    assert REGISTRY["orb"].data_check is None


FIXTURES = Path(__file__).parent / "fixtures" / "nse"


def test_announcements_layout_uses_dissemination_not_broadcast(tmp_path):
    local = tmp_path / "document.pdf"
    local.write_bytes(b"invented original attachment")
    events = load_nse_announcements(
        [FIXTURES / "announcements.csv"], isin_by_symbol={"ALPHA": "INE000TEST01"},
        first_seen_at=ts("2025-02-01"),
        documents={"https://example.invalid/alpha-results.pdf": local},
        annotations={"https://example.invalid/alpha-results.pdf": {"earnings_change": 10},
                     "https://example.invalid/alpha-meeting.pdf": {"scheduled_for": ts("2025-01-03").date()}})
    assert len(events) == 3
    assert events[0].isin == "INE000TEST01"
    assert events[0].disseminated_at == ts("2025-01-01 10:01")
    assert events[0].first_seen_at == ts("2025-02-01")
    assert events[0].document == local.read_bytes()
    assert events[0].doc_hash == hashlib.sha256(local.read_bytes()).hexdigest()
    assert events[0].earnings_change == 10
    assert events[1].kind == "board_meeting"
    assert events[1].scheduled_for == ts("2025-01-03").date()
    assert events[2].disseminated_at is None  # no received/broadcast fallback
    assert events[2].document_format == "export_row"
    assert json.loads(events[2].document)["BROADCAST DATE/TIME"] == "02-Jan-2025 10:00:00"


@pytest.mark.parametrize("kind,filename", [("bulk_deal", "bulk.csv"), ("block_deal", "block.csv")])
def test_deal_layout_does_not_invent_publication_time(kind, filename):
    events = load_nse_deals([FIXTURES / filename], kind=kind, first_seen_at=ts("2025-02-01"))
    assert [e.side for e in events] == ["BUY", "SELL"]
    assert all(e.kind == kind and e.disseminated_at is None for e in events)
    assert REGISTRY["block_buy_continuation"].data_check(bars(events=events)).verdict == "CAN'T TELL"
    assert json.loads(events[0].document)
    verified = load_nse_deals([FIXTURES / filename], kind=kind, disseminated_at=ts("2025-01-01 18:00"))
    assert all(e.disseminated_at == ts("2025-01-01 18:00") for e in verified)


@pytest.mark.parametrize("delay", [1, 5, 15])
@pytest.mark.parametrize("name", ["earnings_continuation", "post_results_orb", "block_buy_continuation"])
def test_event_features_and_signals_are_prefix_stable(name, delay):
    notice = event(kind="bulk_deal", side="BUY") if name == "block_buy_continuation" else event()
    prices = bars(events=[notice])
    prices.loc[ts("2025-01-02 09:30"):ts("2025-01-02 15:25"), "close"] = 102.0
    prices.loc[ts("2025-01-02 09:30"):ts("2025-01-02 15:25"), "high"] = 103.0
    strategy = REGISTRY[name]
    params = {"delay": delay, "holding_days": 3}
    result = check_lookahead(lambda frame: strategy.features(frame, params), prices)
    assert result.verdict == "PASS", result.evidence
    full = strategy.signals(prices, strategy.features(prices, params), params)
    assert full
    for cutoff in [0, 1, 2, 10, 75, 76, 77, 79, 150, 300]:
        prefix = prices.iloc[:cutoff + 1]
        assert strategy.signals(prefix, strategy.features(prefix, params), params) == [
            signal for signal in full if signal.time <= prefix.index[-1]]
        pd.testing.assert_frame_equal(strategy.features(prefix, params), strategy.features(prices, params).iloc[:cutoff + 1])


@pytest.mark.parametrize("holding_days", [1, 3, 5])
def test_earnings_positive_only_and_holding_sessions(holding_days):
    strategy = REGISTRY["earnings_continuation"]
    params = {"holding_days": holding_days, "delay": 1}
    prices = bars(events=[event()])
    signals = strategy.signals(prices, strategy.features(prices, params), params)
    assert [(s.target) for s in signals] == [1, 0]
    assert signals[1].time == prices.index[75 * holding_days]
    for change in (None, 0, -10):
        negative = with_events(prices, [event(earnings_change=change)])
        assert strategy.signals(negative, strategy.features(negative, params), params) == []
        assert strategy.data_check(negative).verdict == ("CAN'T TELL" if change is None else "PASS")


def test_block_sell_is_not_a_buy_and_weekend_is_not_a_session():
    strategy, params = REGISTRY["block_buy_continuation"], {"delay": 15}
    for side, target in [("SELL", []), ("BUY", [Signal(ts("2025-01-06 09:15"), "ALPHA", 1)])]:
        prices = bars(events=[event(kind="block_deal", side=side, disseminated_at=ts("2025-01-03 18:00"))])
        entries = [s for s in strategy.signals(prices, strategy.features(prices, params), params) if s.target]
        assert entries == target


def test_event_trials_filters_and_hashes(tmp_path, monkeypatch):
    import autopsy.strategies as strategies

    event_names = {"earnings_continuation", "post_results_orb", "block_buy_continuation"}
    assert event_names <= REGISTRY.keys()
    assert len([name for name in REGISTRY if "+" not in name]) == 11
    assert all(name + "+results_filter" in REGISTRY for name, rule in REGISTRY.items()
               if rule.mode == "intraday" and "+" not in name)
    original_hash = registry_hash()
    monkeypatch.setattr(strategies, "REGISTRY", {name: rule for name, rule in REGISTRY.items()
                                              if name not in event_names})
    assert registry_hash() != original_hash
    prices = bars(events=[event(), event(kind="bulk_deal", side="BUY")])
    assert hash_prices(prices) != hash_prices(with_events(prices, []))
    assert "expected_bars" in prices.attrs
    log = TrialLog(tmp_path / "trials.jsonl")
    names = sorted(event_names) + ["orb", "orb+results_filter"]
    expected = 0
    for name in names:
        rule = REGISTRY[name]
        results = walk_forward(rule, prices, ts("2025-01-15"), folds=1,
                               trial_log=log, slippage_grid=[10])
        count = 1
        for values in rule.params_grid.values():
            count *= len(values)
        expected += count
        assert len(results) == count
    assert log.trial_count == expected == 19
    assert set(row["strategy"] for row in log.rows()) == set(names)
    assert log.verify()


def test_walkforward_keeps_events_and_fails_missing_data_even_with_profitable_history(tmp_path, monkeypatch):
    import autopsy.research.walkforward as wf

    # Plenty of synthetic PnL must not make missing event times usable.
    monkeypatch.setattr(wf, "daily_net_pnl", lambda record: pd.Series([1., 2., 3.]))
    strategy = REGISTRY["earnings_continuation"]
    invalid = bars(events=[event(disseminated_at=None)])
    log = TrialLog(tmp_path / "trials.jsonl")
    results = walk_forward(strategy, invalid, ts("2025-01-15"), folds=1, trial_log=log, slippage_grid=[10])
    assert all(row.verdict == "CAN'T TELL" and row.net_sharpe is None for row in results)
    complete = [row for row in log.rows() if row["metrics"]["status"] == "complete"]
    assert all(row["metrics"]["folds"][0]["data_check"]["reason"] == "missing dissemination time" for row in complete)


def test_event_times_must_be_aware_and_hashes_match():
    with pytest.raises(ValueError, match="tz-aware"):
        event(disseminated_at=pd.Timestamp("2025-01-01 10:00"))
    with pytest.raises(ValueError, match="hash"):
        event(document=b"changed")


def test_missing_opening_bar_does_not_move_filter_cutoff_or_complete_orb():
    notice = event(disseminated_at=ts("2025-01-02 09:17"))
    prices = bars(events=[notice])
    trimmed = prices.drop(ts("2025-01-02 09:15"))
    # A notice at 09:17 remains too late even if the first observed candle is 09:20.
    base = Strategy("test", "intraday", {}, lambda p, _: p[["symbol"]],
                    lambda p, f, _: [Signal(ts("2025-01-02 09:30"), "ALPHA", 1)])
    filtered = results_day_filter(base)
    assert len(filtered.signals(trimmed, filtered.features(trimmed, {}), {})) == 1
    incomplete = with_events(trimmed, [event()])
    incomplete.loc[ts("2025-01-02 09:30"):ts("2025-01-02 15:25"), "close"] = 102.0
    rule, params = REGISTRY["post_results_orb"], {"delay": 1}
    assert rule.signals(incomplete, rule.features(incomplete, params), params) == []


def test_missing_event_time_reaches_locked_verdict_with_price_coverage_intact(tmp_path):
    from autopsy.research.lock import Lock
    from autopsy.research.walkforward import Pick
    from autopsy.verdict import decide

    prices = bars(events=[event(disseminated_at=None)])
    pick = Pick("earnings_continuation", "swing", {"holding_days": 1, "delay": 1})
    strategy = REGISTRY[pick.strategy]
    signals = strategy.signals(prices, strategy.features(prices, pick.params), pick.params)
    record = run_backtest(prices, signals, "swing", slippage_bps=20, rates=load_rates("zerodha"))
    log = TrialLog(tmp_path / "trials.jsonl")
    log.append(pick.strategy, pick.params, ["development"], {"selected": True})
    path = tmp_path / "lock.jsonl"
    Lock.create(path, hash_prices(prices), registry_hash(), [pick], log.head,
                locked_start=prices.index.min(), locked_end=prices.index.max() + pd.Timedelta(minutes=5),
                trial_log_path=log.path)
    result = decide(pick, record, [], Lock.open(path))
    checks = {check.name: check for check in result.checks}
    assert checks["lock"].verdict == checks["data"].verdict == "PASS"
    assert checks["event_data"].verdict == "CAN'T TELL"
    assert result.verdict == "NO-GO"
    assert "missing dissemination time" in result.reasons
