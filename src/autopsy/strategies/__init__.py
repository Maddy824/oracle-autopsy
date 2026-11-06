"""Fixed research candidates; adding or changing a rule changes the registry hash."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import inspect
import json
from types import MappingProxyType
from typing import Literal

import pandas as pd

from autopsy.engine import Rebalance, Signal
from autopsy.checks import CheckResult


@dataclass(frozen=True)
class Strategy:
    name: str
    mode: Literal["intraday", "swing"]
    params_grid: Mapping[str, Sequence]
    features: Callable[[pd.DataFrame, dict], pd.DataFrame]
    signals: Callable[[pd.DataFrame, pd.DataFrame, dict], list[Signal | Rebalance]]
    data_check: Callable[[pd.DataFrame], CheckResult] | None = None

    def __post_init__(self):
        # Copy before freezing so callers cannot mutate a registered grid through
        # the original dict/list. Tuples retain the list's declared grid order.
        object.__setattr__(self, "params_grid", MappingProxyType({
            key: tuple(values) for key, values in self.params_grid.items()
        }))


from autopsy.strategies import earnings_reaction, events, intraday, swing, weekly_loser_reversal, monthly_momentum  # noqa: E402


_base_registry = {
    strategy.name: strategy for strategy in (
        Strategy("orb", "intraday", {"minutes": [15, 30]}, intraday.orb_features, intraday.orb_signals),
        Strategy("vwap_revert", "intraday", {"deviation": [1.0, 1.5, 2.0]}, intraday.vwap_features, intraday.vwap_signals),
        Strategy("first_hour_momentum", "intraday", {"threshold": [0.5, 1.0]}, intraday.momentum_features, intraday.momentum_signals),
        Strategy("gap_play", "intraday", {"gap": [1, 2], "mode": ["fade", "continue"]}, intraday.gap_features, intraday.gap_signals),
        Strategy("nday_breakout", "swing", {"n": [20, 55]}, swing.breakout_features, swing.breakout_signals),
        Strategy("trend_pullback", "swing", {"ma": [50, 100], "pullback": [3, 5]}, swing.pullback_features, swing.pullback_signals),
        Strategy("short_reversal", "swing", {"lookback": [3, 5]}, swing.reversal_features, swing.reversal_signals),
        Strategy("earnings_reaction", "swing", {"variant": list(earnings_reaction.VARIANTS)},
                 earnings_reaction.features, earnings_reaction.signals, earnings_reaction.data_check),
        Strategy("weekly_loser_reversal", "swing", {"variant": ["h5", "h10"]},
                 weekly_loser_reversal.features, weekly_loser_reversal.signals, weekly_loser_reversal.data_check),
        Strategy("monthly_momentum", "swing", {"variant": ["M12", "M12V"]},
                 monthly_momentum.features, monthly_momentum.signals, monthly_momentum.data_check),
        Strategy("earnings_continuation", "swing", {"holding_days": [1, 3, 5], "delay": events.DELAYS},
                 events.earnings_features, events.earnings_signals, events.earnings_data_check),
        Strategy("post_results_orb", "intraday", {"delay": events.DELAYS},
                 events.post_results_features, events.post_results_signals, events.results_data_check),
        Strategy("block_buy_continuation", "swing", {"delay": events.DELAYS},
                 events.deals_features, events.deals_signals, events.deals_data_check),
    )
}
_filtered = [events.results_day_filter(strategy) for strategy in _base_registry.values()
             if strategy.mode == "intraday"]
REGISTRY: Mapping[str, Strategy] = MappingProxyType({
    **_base_registry, **{strategy.name: strategy for strategy in _filtered},
})
del _base_registry, _filtered


def registry_hash() -> str:
    """SHA-256 of sorted names, modes, grids and implementation source.

    Include both callbacks and their modules: edits to shared feature/signal
    helpers must invalidate a lock just as direct callback edits do.
    """
    records = []
    from autopsy import engine
    from autopsy.news import events as event_records, nse_filings
    sources = {module.__name__: inspect.getsource(module)
               for module in (inspect.getmodule(registry_hash), event_records, nse_filings, engine)}
    for key, strategy in sorted(REGISTRY.items()):
        callbacks = (strategy.features, strategy.signals) + ((strategy.data_check,) if strategy.data_check else ())
        records.append({
            "key": key, "name": strategy.name, "mode": strategy.mode,
            "grid": {name: list(values) for name, values in strategy.params_grid.items()},
            "callbacks": [inspect.getsource(callback) for callback in callbacks],
        })
        for callback in callbacks:
            module = inspect.getmodule(callback)
            sources[module.__name__] = inspect.getsource(module)
    payload = json.dumps({"strategies": records, "sources": sources}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
