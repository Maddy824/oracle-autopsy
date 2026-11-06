"""Development-only selection using equal, chronological session folds."""

from dataclasses import dataclass
from itertools import product
from math import isfinite

import numpy as np
import pandas as pd

from autopsy.costs import load_rates
from autopsy.engine import run_backtest
from autopsy.stats import MinTradesError, daily_net_pnl, sharpe
from autopsy.research.trials import TrialLog, _json

RULE = "best_median_fold_net_sharpe_at_2x_slippage"
GRIDS = {"intraday": (10, 25, 50), "swing": (5, 10, 25)}


def slippage_grid_for(strategy):
    """Managed daily families pre-register a fixed 10 bps base."""
    return (10,) if strategy.name in ("earnings_reaction", "weekly_loser_reversal") else GRIDS[strategy.mode]


@dataclass(frozen=True)
class Pick:
    strategy: str
    mode: str
    params: dict
    base_slippage_bps: float = 10
    rule: str = RULE
    median_fold_net_sharpe: float | None = None
    trial_log_path: str | None = None

    def __post_init__(self):
        if self.mode not in GRIDS or self.rule != RULE:
            raise ValueError("unsupported mode or selection rule")
        if not isfinite(self.base_slippage_bps) or not 0 <= self.base_slippage_bps < 5000:
            raise ValueError("invalid base slippage")


@dataclass(frozen=True)
class FoldResult:
    strategy: str
    mode: str
    params: dict
    base_slippage_bps: float
    fold: int
    start: pd.Timestamp
    end: pd.Timestamp  # exclusive
    net_sharpe: float | None
    net_profit: float | None
    verdict: str
    trial_log_path: str
    folds: int

    @property
    def slippage_bps(self):
        return 2 * self.base_slippage_bps


def _time(value):
    value = pd.Timestamp(value)
    if pd.isna(value) or value.tz is None:
        raise ValueError("window timestamps must be tz-aware")
    return value.tz_convert("Asia/Kolkata")


def walk_forward(strategy, prices, dev_end, folds=4, *, trial_log=None, slippage_grid=None, rates=None):
    """Try the declared parameter/slippage grid, logging before each attempt.

    dev_end is exclusive. Slice by index BEFORE reading any price column.
    Each fold starts with fresh capital; earlier development bars warm features,
    but never contribute PnL. Insufficient-trade folds cannot win selection.
    """
    dev_end = _time(dev_end)
    if isinstance(folds, bool) or not isinstance(folds, int) or folds < 1:
        raise ValueError("folds must be a positive integer")
    dev = prices.loc[prices.index < dev_end].copy()
    # Event evidence and the independent schedule must survive window slicing.
    dev.attrs = {key: value for key, value in prices.attrs.items()
                 if key in {"events", "expected_bars", "bar_interval", "index_symbol", "index_prices"}}
    if dev.empty or not dev.index.is_monotonic_increasing:
        raise ValueError("ordered development bars required")
    days = dev.index.normalize().unique()
    if len(days) < folds:
        raise ValueError("not enough development sessions")
    groups = np.array_split(np.arange(len(days)), folds)
    boundaries = [days[group[0]] for group in groups] + [dev_end]
    log = trial_log if trial_log is not None else TrialLog()
    rates = rates if rates is not None else load_rates("zerodha")
    allowed = slippage_grid_for(strategy)
    grid = allowed if slippage_grid is None else tuple(slippage_grid)
    if not grid or any(value not in allowed for value in grid) or len(set(grid)) != len(grid):
        raise ValueError("slippage grid must be a subset of the declared mode grid")
    results = []
    keys = sorted(strategy.params_grid)
    for values in product(*(strategy.params_grid[key] for key in keys)):
        params = dict(zip(keys, values))
        for base in grid:
            window = [boundaries[0].isoformat(), dev_end.isoformat()]
            attempt = {"status": "started", "base_slippage_bps": base, "slippage_bps": 2 * base}
            attempt_head = log.append(strategy.name, params, window, attempt)
            metrics = []
            for fold in range(folds):
                start, end = boundaries[fold:fold + 2]
                history = dev.loc[dev.index < end]
                data_check = strategy.data_check(history) if strategy.data_check else None
                features = strategy.features(history, params)
                signals = [signal for signal in strategy.signals(history, features, params)
                           if start <= signal.time < end]
                record = run_backtest(history.loc[history.index >= start], signals, strategy.mode,
                                      slippage_bps=2 * base, rates=rates)
                try:
                    pnl = daily_net_pnl(record)
                    prior = record.start_cash + pnl.cumsum().shift(1, fill_value=0)
                    score, profit, status = sharpe(pnl / prior), float(pnl.sum()), "PASS"
                except MinTradesError:
                    score, profit, status = None, None, "CAN'T TELL"
                if data_check is not None and data_check.verdict != "PASS":
                    score, profit, status = None, None, data_check.verdict
                results.append(FoldResult(strategy.name, strategy.mode, params.copy(), base, fold,
                                          start, end, score, profit, status, str(log.path.resolve()), folds))
                metrics.append({"fold": fold, "net_sharpe": score, "net_profit": profit, "verdict": status,
                                **({"data_check": data_check.evidence} if data_check else {})})
            log.append(strategy.name, params, window, {"status": "complete", "attempt": attempt_head,
                                                       "base_slippage_bps": base, "folds": metrics})
    return results


def select(results, rule=RULE):
    """Return one Pick for one mode; invoke separately for intraday and swing.

    All folds must be present and usable. Ties use strategy, canonical params,
    then base slippage, so input iteration order cannot choose the winner.
    """
    results = list(results)
    if rule != RULE or not results:
        raise ValueError("known selection rule and nonempty results required")
    if len({result.mode for result in results}) != 1:
        raise ValueError("select one mode at a time")
    groups = {}
    for result in results:
        key = (result.strategy, _json(result.params), result.base_slippage_bps)
        groups.setdefault(key, []).append(result)
    candidates = []
    for key, group in groups.items():
        expected = group[0].folds
        if (len(group) == expected and {row.fold for row in group} == set(range(expected))
                and all(row.verdict == "PASS" and row.net_sharpe is not None
                        and isfinite(row.net_sharpe) for row in group)):
            candidates.append((float(np.median([row.net_sharpe for row in group])), key, group[0]))
    if not candidates:
        raise MinTradesError("no candidate has all usable walk-forward folds")
    median, _, winner = min(candidates, key=lambda item: (-item[0], item[1]))
    return Pick(winner.strategy, winner.mode, winner.params.copy(), winner.base_slippage_bps,
                rule, median, winner.trial_log_path)
