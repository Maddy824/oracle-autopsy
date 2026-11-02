"""Fixed research candidates; adding or changing a rule changes the registry hash."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import inspect
import json
from types import MappingProxyType
from typing import Literal

import pandas as pd

from autopsy.engine import Signal


@dataclass(frozen=True)
class Strategy:
    name: str
    mode: Literal["intraday", "swing"]
    params_grid: Mapping[str, Sequence]
    features: Callable[[pd.DataFrame, dict], pd.DataFrame]
    signals: Callable[[pd.DataFrame, pd.DataFrame, dict], list[Signal]]

    def __post_init__(self):
        # Copy before freezing so callers cannot mutate a registered grid through
        # the original dict/list. Tuples retain the list's declared grid order.
        object.__setattr__(self, "params_grid", MappingProxyType({
            key: tuple(values) for key, values in self.params_grid.items()
        }))


from autopsy.strategies import intraday, swing  # noqa: E402


REGISTRY: Mapping[str, Strategy] = MappingProxyType({
    strategy.name: strategy for strategy in (
        Strategy("orb", "intraday", {"minutes": [15, 30]}, intraday.orb_features, intraday.orb_signals),
        Strategy("vwap_revert", "intraday", {"deviation": [1.0, 1.5, 2.0]}, intraday.vwap_features, intraday.vwap_signals),
        Strategy("first_hour_momentum", "intraday", {"threshold": [0.5, 1.0]}, intraday.momentum_features, intraday.momentum_signals),
        Strategy("gap_play", "intraday", {"gap": [1, 2], "mode": ["fade", "continue"]}, intraday.gap_features, intraday.gap_signals),
        Strategy("nday_breakout", "swing", {"n": [20, 55]}, swing.breakout_features, swing.breakout_signals),
        Strategy("trend_pullback", "swing", {"ma": [50, 100], "pullback": [3, 5]}, swing.pullback_features, swing.pullback_signals),
        Strategy("short_reversal", "swing", {"lookback": [3, 5]}, swing.reversal_features, swing.reversal_signals),
    )
})


def registry_hash() -> str:
    """SHA-256 of sorted names, modes, grids and implementation source.

    Include both callbacks and their modules: edits to shared feature/signal
    helpers must invalidate a lock just as direct callback edits do.
    """
    records = []
    sources = {__name__: inspect.getsource(inspect.getmodule(registry_hash))}
    for key, strategy in sorted(REGISTRY.items()):
        callbacks = (strategy.features, strategy.signals)
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
