from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from autopsy.checks import CheckResult
from autopsy.costs import load_rates
from autopsy.engine import run_backtest
from autopsy.research.lock import Lock, hash_prices
from autopsy.research.trials import TrialLog
from autopsy.research.walkforward import Pick
from autopsy.strategies import REGISTRY, registry_hash
from autopsy.verdict import decide
import autopsy.verdict as verdict_module
from synthetic_bars import opening_range_bars, random_walk_bars


def execute(bars, pick, slippage=None):
    strategy = REGISTRY[pick.strategy]
    signals = strategy.signals(bars, strategy.features(bars, pick.params), pick.params)
    return run_backtest(bars, signals, pick.mode, slippage_bps=(2 * pick.base_slippage_bps
                        if slippage is None else slippage), rates=load_rates("zerodha"))


@pytest.fixture(scope="module")
def edge():
    pick = Pick("orb", "intraday", {"minutes": 15}, base_slippage_bps=10)
    bars = opening_range_bars(days=40)
    return pick, bars, execute(bars, pick)


def seal(tmp_path, pick, bars, *, window=None):
    window = bars if window is None else window
    log = TrialLog(tmp_path / "trials.jsonl")
    log.append(pick.strategy, pick.params, ["development"], {"selected": True})
    path = tmp_path / "lock.jsonl"
    Lock.create(path, hash_prices(bars), registry_hash(), [pick], log.head,
                locked_start=window.index.min(), locked_end=window.index.max() + pd.Timedelta(minutes=5),
                trial_log_path=log.path)
    return Lock.open(path)


@pytest.mark.parametrize("openings", [2, 3])
def test_second_opening_fails(tmp_path, edge, openings):
    pick, bars, record = edge
    lock = seal(tmp_path, pick, bars)
    for _ in range(openings - 1):
        Lock.open(lock.path)
    # An old handle must see later openings too.
    result = decide(pick, record, [], lock)
    assert result.verdict == "NO-GO"
    assert f"holdout opened {openings} times" in result.reasons


def test_legacy_planted_edge_keeps_portfolio_gate(tmp_path, edge):
    pick, bars, record = edge
    result = decide(pick, record, [], seal(tmp_path, pick, bars))
    assert result.verdict == "NO-GO", result
    assert next(c for c in result.checks if c.name == "random_portfolio").verdict == "CAN'T TELL"
    assert verdict_module._finish([c for c in result.checks if c.name != "random_portfolio"],
                                  result.stats).verdict == "GO"
    assert result.stats["trades"] == 40
    assert result.stats["bootstrap_lower"] > 0
    assert result.stats["net_profit"] > result.stats["random_entry_p95"]
    assert result.stats["random_entry_runs"] == 1000
    assert result.stats["slippage_bps"] == 20
    assert result.stats["max_drawdown"] <= .15
    assert result.stats["dsr_heuristic"] is True
    assert "nifty_etf_sharpe" in result.stats
    print("PLANTED_EDGE_STATS", result.stats)


@pytest.mark.parametrize("minutes", [15, 30])
def test_random_walk_gets_no_go(tmp_path, minutes):
    pick = Pick("orb", "intraday", {"minutes": minutes}, base_slippage_bps=10)
    bars = random_walk_bars(days=40, seed=17)
    result = decide(pick, execute(bars, pick), [], seal(tmp_path, pick, bars))
    assert result.verdict == "NO-GO"
    assert result.stats["trades"] >= 30


@pytest.mark.parametrize("drop_kind", ["interior", "whole_session"])
def test_missing_bars_cant_tell(tmp_path, edge, drop_kind):
    pick, bars, _ = edge
    if drop_kind == "interior":
        missing = np.random.default_rng(3).choice(len(bars), int(len(bars) * .03), replace=False)
        damaged = bars.iloc[np.setdiff1d(np.arange(len(bars)), missing)].copy()
    else:
        damaged = bars.loc[bars.index.normalize() > bars.index.normalize().unique()[1]].copy()
    # Seal the actually observed snapshot, so coverage alone must block GO.
    result = decide(pick, execute(damaged, pick), [], seal(tmp_path, pick, damaged, window=bars))
    assert result.verdict == "NO-GO"
    check = next(check for check in result.checks if check.name == "data")
    assert check.verdict == "CAN'T TELL"
    assert check.evidence["missing_fraction"] > .02
    assert next(check for check in result.checks if check.name == "lock").verdict == "PASS"


@pytest.mark.parametrize("case", ["cant_tell", "fail", "base_slippage", "few_trades", "outside_window",
                                  "wrong_pick", "missing_schedule", "trial_tamper", "lock_tamper", "context_only",
                                  "zero_bootstrap", "tied_baseline", "drawdown_at_limit", "drawdown_over_limit"])
def test_any_cant_tell_blocks_go(tmp_path, edge, case, monkeypatch):
    pick, bars, record = edge
    lock = seal(tmp_path, pick, bars)
    checks = []
    if case in ("cant_tell", "fail"):
        checks = [CheckResult("additional_audit", "CAN'T TELL" if case == "cant_tell" else "FAIL", {})]
    elif case == "base_slippage":
        record = execute(bars, pick, slippage=10)
    elif case == "few_trades":
        record = execute(bars.iloc[:75 * 20], pick)
    elif case == "outside_window":
        outside = bars.copy()
        outside.index += pd.DateOffset(years=2)
        record = execute(outside, pick)
    elif case == "wrong_pick":
        pick = replace(pick, params={"minutes": 30})
    elif case == "missing_schedule":
        bars = bars.copy()
        bars.attrs.clear()
        record = execute(bars, pick)
    elif case == "trial_tamper":
        (tmp_path / "trials.jsonl").write_text("")
    elif case == "lock_tamper":
        lock.path.write_text(lock.path.read_text().replace('"base_slippage_bps":10', '"base_slippage_bps":25'))
    elif case == "context_only":
        checks = [CheckResult("dsr", "FAIL", {}), CheckResult("nifty_etf", "CAN'T TELL", {})]
        monkeypatch.setattr(verdict_module, "deflated_sharpe", lambda *args: 0.)
        record = replace(record)
        days = bars.index.normalize().unique()
        benchmark = pd.Series(100 * np.cumprod(1.01 + .00001 * np.sin(np.arange(len(days)))), index=days)
        record.reported_equity.attrs["nifty_etf_equity"] = benchmark
    elif case == "zero_bootstrap":
        monkeypatch.setattr(verdict_module, "bootstrap_lower", lambda *args, **kwargs: 0.)
    elif case == "tied_baseline":
        profit = float(verdict_module.daily_net_pnl(record).sum())
        monkeypatch.setattr(verdict_module, "random_entry_baseline", lambda *args, **kwargs: np.full(1000, profit))
    elif case in ("drawdown_at_limit", "drawdown_over_limit"):
        monkeypatch.setattr(verdict_module, "max_drawdown", lambda _: -.15 if case == "drawdown_at_limit" else -.15001)
    result = decide(pick, record, checks, lock)
    assert result.verdict == "NO-GO"  # legacy sampler cannot lift the portfolio gate
    # Keep exercising all the other gates independently of that new blocker.
    without_portfolio = verdict_module._finish(
        [c for c in result.checks if c.name != "random_portfolio"], result.stats)
    assert without_portfolio.verdict == ("GO" if case in ("context_only", "drawdown_at_limit") else "NO-GO"), result
    if case == "context_only":
        assert result.stats["dsr"] == 0.
        assert result.stats["beats_nifty_etf_sharpe"] is False
