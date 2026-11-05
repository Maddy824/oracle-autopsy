"""Locked-window GO gate: net of execution costs, before income tax."""

from dataclasses import dataclass
import json
from math import isclose
from typing import Literal

import numpy as np
import pandas as pd

from autopsy.checks import CheckResult
from autopsy.checks.ledger_check import check_ledger
from autopsy.checks.lookahead import check_determinism, check_lookahead
from autopsy.costs import RateTable, trade_costs
from autopsy.stats import (MinTradesError, _round_trips, bootstrap_lower, daily_net_pnl,
                           deflated_sharpe, max_drawdown, random_entry_baseline, sharpe)
from autopsy.strategies import REGISTRY

# These labels are report context even if a caller supplies a non-PASS result.
CONTEXT_CHECKS = {"dsr", "deflated_sharpe", "nifty_etf", "nifty_etf_comparison"}


@dataclass
class Verdict:
    verdict: Literal["GO", "NO-GO"]
    reasons: list[str]
    checks: list[CheckResult]
    stats: dict


def _data_check(prices, lock):
    schedule = prices.attrs.get("expected_bars")
    if schedule is None:
        return CheckResult("data", "CAN'T TELL", {"reason": "expected bar schedule unavailable"})
    try:
        if isinstance(schedule, str):
            schedule = json.loads(schedule)
        expected = {(pd.Timestamp(time), symbol) for time, symbol in schedule
                    if lock.locked_start <= pd.Timestamp(time) < lock.locked_end}
        actual = set(zip(prices.index, prices.symbol))
        if not expected:
            raise ValueError("empty expected schedule")
        missing = len(expected - actual) / len(expected)
        status = "CAN'T TELL" if missing > .02 else "PASS"
        if actual - expected:
            status = "FAIL"
        return CheckResult("data", status, {"missing_fraction": missing,
                                           "expected_bars": len(expected), "actual_bars": len(actual)})
    except (ValueError, TypeError):
        return CheckResult("data", "CAN'T TELL", {"reason": "invalid expected bar schedule"})


def _execution_check(pick, record):
    config = record.reported_equity.attrs.get("autopsy_execution", {})
    if not config or not {"mode", "slippage_bps", "rates"} <= config.keys():
        return CheckResult("costs", "CAN'T TELL", {"reason": "execution metadata unavailable"})
    if config["mode"] != pick.mode or config["slippage_bps"] != 2 * pick.base_slippage_bps:
        return CheckResult("costs", "FAIL", {"reason": "record must use doubled base slippage",
                                            "required_slippage_bps": 2 * pick.base_slippage_bps})
    try:
        rates = RateTable(**config["rates"])
        segment = "intraday_equity" if pick.mode == "intraday" else "delivery_equity"
        opens = {(time, symbol): value for time, symbol, value
                 in zip(record.prices.index, record.prices.symbol, record.prices.open)}
        sold = set()
        for fill in record.fills:
            key = (fill.time.normalize(), fill.symbol)
            expected_price = opens[fill.time, fill.symbol] * (
                1 + (1 if fill.side == "BUY" else -1) * config["slippage_bps"] / 10_000)
            expected_fee = trade_costs(fill.side, fill.qty * fill.price, segment, rates,
                                       symbol_sold_today=key in sold).total
            if not isclose(fill.price, expected_price, abs_tol=1e-8) or not isclose(fill.fee, expected_fee, abs_tol=1e-8):
                return CheckResult("costs", "FAIL", {"reason": "fill does not match recorded execution costs"})
            if fill.side == "SELL":
                sold.add(key)
        return CheckResult("costs", "PASS", {"slippage_bps": config["slippage_bps"], "tax_basis": "before tax"})
    except (KeyError, TypeError, ValueError):
        return CheckResult("costs", "CAN'T TELL", {"reason": "unverifiable execution costs"})


def _finish(checks, stats):
    reasons = []
    for check in checks:
        if check.name not in CONTEXT_CHECKS and check.verdict != "PASS":
            reasons.append(check.evidence.get("reason", f"{check.name}: {check.verdict}"))
    return Verdict("NO-GO" if reasons else "GO", list(dict.fromkeys(reasons)), checks, stats)


def decide(pick, locked_record, checks, lock):
    """Audit a freshly funded locked-window run at twice pick.base_slippage_bps.

    Reject out-of-window records instead of slicing contaminated equity/fills.
    Coverage uses prices.attrs['expected_bars'], JSON text (or a list) of
    (ISO time, symbol) pairs from an independent session schedule, included in
    the locked hash. JSON text avoids pandas repeatedly deep-copying the list.
    An optional equity.attrs['nifty_etf_equity'] Series is reported on the same
    observed sessions. Missing benchmark data and DSR never affect GO.
    """
    record = locked_record
    checks = list(checks)
    stats = {"base_slippage_bps": pick.base_slippage_bps,
             "slippage_bps": 2 * pick.base_slippage_bps, "tax_basis": "before tax",
             "dsr": None, "dsr_heuristic": True, "nifty_etf_sharpe": None,
             "beats_nifty_etf_sharpe": None}
    try:
        openings = lock.openings
        valid = lock.verify() and lock.matches(pick, record.prices)
        reason = f"holdout opened {openings} times" if openings != 1 else "lock integrity mismatch"
        checks.append(CheckResult("lock", "PASS" if valid and openings == 1 else "FAIL",
                                  {"openings": openings, **({"reason": reason} if not valid or openings != 1 else {})}))
    except (ValueError, OSError, KeyError):
        checks.append(CheckResult("lock", "FAIL", {"reason": "lock integrity mismatch"}))
    indices = (record.prices.index, record.reported_equity.index,
               pd.DatetimeIndex([fill.time for fill in record.fills]))
    if any(len(index) and ((index < lock.locked_start) | (index >= lock.locked_end)).any()
           for index in indices):
        checks.append(CheckResult("window", "FAIL", {"reason": "record includes bars or fills outside locked window"}))
        return _finish(checks, stats)
    checks.append(_data_check(record.prices, lock))
    execution = _execution_check(pick, record)
    checks.append(execution)
    checks.append(check_ledger(record))
    strategy = REGISTRY.get(pick.strategy)
    if strategy is None or strategy.mode != pick.mode:
        checks.append(CheckResult("strategy", "FAIL", {"reason": "pick is not a registered strategy"}))
        return _finish(checks, stats)
    if strategy.data_check is not None:
        checks.append(strategy.data_check(record.prices))
    baseline_options = {}
    if pick.strategy == "earnings_reaction":
        from autopsy.strategies.earnings_reaction import event_sessions
        baseline_options["eligible_signal_days"] = {day for _, day in event_sessions(record.prices)}
        stats["random_entry_matching"] = "traded symbols, event-season signal days, quantities, realized holding durations"
        checks.append(CheckResult("random_portfolio", "CAN'T TELL", {
            "reason": "Season-matched random entries still allow overlapping trades without cash or five-position limits; "
                      "dynamic sizing and ATR stops are not replayed. Pre-registered portfolio baseline remains unavailable."}))
    feature_fn = lambda prices: strategy.features(prices, pick.params)
    names = {check.name for check in checks}
    if "lookahead" not in names:
        checks.append(check_lookahead(feature_fn, record.prices))
    if "determinism" not in names:
        checks.append(check_determinism(feature_fn, record.prices))
    try:
        stats["trades"] = len(_round_trips(record))
        pnl = daily_net_pnl(record)
    except MinTradesError as exc:
        checks.append(CheckResult("trades", "CAN'T TELL", {"reason": str(exc)}))
        return _finish(checks, stats)
    except ValueError as exc:
        checks.append(CheckResult("trades", "CAN'T TELL", {"reason": str(exc)}))
        return _finish(checks, stats)
    checks.append(CheckResult("trades", "PASS", {"trades": stats["trades"]}))
    if execution.verdict != "PASS":
        return _finish(checks, stats)
    prior = record.start_cash + pnl.cumsum().shift(1, fill_value=0)
    returns = pnl / prior.replace(0, np.nan)
    stats.update(mean_daily_net_pnl=float(pnl.mean()), net_profit=float(pnl.sum()),
                 bootstrap_lower=bootstrap_lower(pnl, alpha=.05, n=5000, seed=0),
                 max_drawdown=-max_drawdown(np.r_[record.start_cash, record.reported_equity]),
                 sharpe=sharpe(returns) if np.isfinite(returns).all() else None,
                 random_entry_runs=1000, trial_count=lock.trial_count)
    checks.append(CheckResult("bootstrap", "PASS" if stats["mean_daily_net_pnl"] > 0 and stats["bootstrap_lower"] > 0 else "FAIL",
                              {"lower": stats["bootstrap_lower"], "alpha": .05}))
    try:
        baseline = random_entry_baseline(record, record.prices, runs=1000, seed=0, **baseline_options)
        stats["random_entry_p95"] = float(np.quantile(baseline, .95))
        checks.append(CheckResult("random_entry", "PASS" if stats["net_profit"] > stats["random_entry_p95"] else "FAIL",
                                  {"p95": stats["random_entry_p95"], "runs": 1000}))
    except ValueError as exc:
        checks.append(CheckResult("random_entry", "CAN'T TELL", {"reason": str(exc)}))
    checks.append(CheckResult("drawdown", "PASS" if stats["max_drawdown"] <= .15 else "FAIL",
                              {"max_drawdown": stats["max_drawdown"], "limit": .15}))
    if stats["sharpe"] is None:
        checks.append(CheckResult("account_returns", "FAIL", {"reason": "account equity exhausted"}))
        return _finish(checks, stats)
    centered = returns.to_numpy() - returns.mean()
    variance = float(np.mean(centered ** 2))
    if variance and len(returns) >= 2:
        skew = float(np.mean(centered ** 3) / variance ** 1.5)
        kurt = max(float(np.mean(centered ** 4) / variance ** 2), skew ** 2 + 1)
        try:
            stats["dsr"] = deflated_sharpe(stats["sharpe"], max(1, lock.trial_count), len(returns), skew, kurt)
        except ValueError:
            pass  # Descriptive heuristic may be undefined; never a gate.
    benchmark = record.reported_equity.attrs.get("nifty_etf_equity")
    if isinstance(benchmark, pd.Series) and isinstance(benchmark.index, pd.DatetimeIndex) and benchmark.index.tz is not None:
        benchmark = benchmark.copy()
        benchmark.index = benchmark.index.tz_convert("Asia/Kolkata")
        # Daily ETF quotes are commonly midnight-stamped; match sessions, not
        # the intraday start's clock time, and exclude every other session.
        benchmark = benchmark.loc[benchmark.index.normalize().isin(pnl.index)]
        daily = benchmark.groupby(benchmark.index.normalize()).last()
        if daily.index.equals(pnl.index) and np.isfinite(daily).all() and (daily > 0).all():
            stats["nifty_etf_sharpe"] = sharpe(daily.pct_change().dropna())
            stats["beats_nifty_etf_sharpe"] = stats["sharpe"] >= stats["nifty_etf_sharpe"]
    return _finish(checks, stats)
