"""Record Gymnasium's reset/step protocol without importing Gymnasium."""

from collections.abc import Callable, Iterable
from typing import Any

import pandas as pd

from autopsy.types import Fill, RunRecord, _validate_start_cash, _validated_prices


def record_gym_run(
    env: Any,
    policy: Callable[[Any, int], Any],
    fill_extractor: Callable[[Any, dict], Iterable[Fill]],
    equity_extractor: Callable[[Any, dict], tuple[pd.Timestamp, float]],
) -> RunRecord:
    """Record reset equity and each step through termination OR truncation.

    The caller supplies ``env.audit_prices`` (canonical OHLCV DataFrame) and
    ``env.initial_balance``. Extractors receive (env, info) after reset and each
    step. The fill extractor returns ONLY newly executed fills, including forced
    exits; the equity extractor returns (time of valuation, reported equity).
    A fresh stateful extractor is needed per run. Policy step numbers start at 0.

    Keep only observed bars; never fabricate equity for warmup or unused tail
    bars. Intermediate missing observations are errors. The finite price panel
    bounds the episode, so an environment that never finishes cannot hang.
    """
    prices = _validated_prices(env.audit_prices).sort_index(kind="stable")
    start_cash = float(env.initial_balance)
    _validate_start_cash(start_cash)
    times, values, fills = [], [], []

    def capture(info):
        time, value = equity_extractor(env, info)
        if not isinstance(time, pd.Timestamp) or time.tz is None or pd.isna(time):
            raise ValueError("equity extractor must return a tz-aware timestamp")
        if time not in prices.index or (times and time <= times[-1]):
            raise ValueError("equity timestamps must be increasing price timestamps")
        times.append(time)
        values.append(value)
        fills.extend(fill_extractor(env, info))

    obs, info = env.reset()
    capture(info)
    for step in range(len(prices.index.unique())):
        obs, _reward, terminated, truncated, info = env.step(policy(obs, step))
        capture(info)
        if terminated or truncated:
            break
    else:
        raise ValueError("environment did not finish within the price history")

    observed = prices.loc[(prices.index >= times[0]) & (prices.index <= times[-1])]
    if not observed.index.unique().equals(pd.DatetimeIndex(times)):
        raise ValueError("environment skipped price timestamps")
    return RunRecord(fills, pd.Series(values, index=times, name="equity", dtype=float),
                     observed, start_cash)
