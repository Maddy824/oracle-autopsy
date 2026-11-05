"""Observed-session schedules shared by every price loader.

For every trading day present in ANY symbol, form the inclusive grid from
that day's earliest to latest timestamp across ALL symbols at the dataset
interval, then cross it with EVERY dataset symbol. Store [ISO time, symbol]
pairs as JSON text in attrs['expected_bars'] for verdict._data_check. JSON
avoids expensive nested-list copies in pandas group operations. This detects
interior gaps and symbol/day omissions, but cannot detect days or session
edges missing from every symbol. No exchange holiday calendar is invented.

Build the schedule before filtering research windows or dropping rows; those
operations must preserve it. combine_prices rebuilds the union schedule and
also retains existing expectations so it cannot erase previously known gaps.
"""

import json
from datetime import time

import numpy as np
import pandas as pd

from autopsy.types import _ist_index, _validated_prices


def intraday_research_prices(prices):
    """Copy the common pre-15:15 IST research session and its expected slots.

    Filter the existing schedule, rather than rebuilding from observed bars:
    rebuilding would erase genuine missing bars at the remaining session edges.
    The source frame and its raw snapshot are untouched. Call before features,
    signals, quality checks and research snapshots, for intraday research only.
    """
    cutoff = time(15, 15)
    index = _ist_index(prices.index, "prices")
    result = prices.loc[index.time < cutoff].copy()
    result.index = index[index.time < cutoff]
    schedule = prices.attrs.get("expected_bars")
    if schedule is not None:
        if isinstance(schedule, str):
            schedule = json.loads(schedule)
        result.attrs["expected_bars"] = json.dumps(
            [pair for pair in schedule
             if pd.Timestamp(pair[0]).tz_convert("Asia/Kolkata").time() < cutoff],
            separators=(",", ":"),
        )
    return result


def with_schedule(prices, interval):
    """Return validated IST prices with a dataset interval and session grid."""
    result = _validated_prices(prices).sort_index(kind="stable")
    offset = pd.tseries.frequencies.to_offset(interval)
    if offset.n <= 0:
        raise ValueError("bar interval must be positive")
    numeric = result[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or (numeric[:, :4] <= 0).any() or (numeric[:, 4] < 0).any():
        raise ValueError("prices require positive finite OHLC and nonnegative finite volume")
    if ((result.high < result[["open", "close", "low"]].max(axis=1)).any()
            or (result.low > result[["open", "close"]].min(axis=1)).any()):
        raise ValueError("invalid OHLC range")
    symbols = sorted(result.symbol.unique())
    expected = []
    for _, bars in result.groupby(result.index.normalize(), sort=True):
        # Daily/weekly/monthly datasets have a single bar on an observed date.
        if len(bars.index.unique()) == 1:
            grid = bars.index.unique()
        else:
            grid = pd.date_range(bars.index.min(), bars.index.max(), freq=offset)
        if not bars.index.isin(grid).all():
            raise ValueError("bar timestamps do not align with the dataset interval")
        expected.extend((time.isoformat(), symbol) for time in grid for symbol in symbols)
    result.attrs["bar_interval"] = offset.freqstr
    result.attrs["expected_bars"] = json.dumps(expected, separators=(",", ":"))
    return result


def combine_prices(frames, interval=None):
    """Combine chunks/symbols at one interval, retaining known missing bars."""
    frames = list(frames)
    if not frames:
        raise ValueError("at least one price frame is required")
    bases = {f.attrs.get("price_basis", "raw") for f in frames}
    if len(bases) != 1:
        raise ValueError("cannot combine raw and adjusted prices")
    intervals = {pd.tseries.frequencies.to_offset(f.attrs["bar_interval"]).freqstr
                 for f in frames if "bar_interval" in f.attrs}
    if interval is not None:
        intervals.add(pd.tseries.frequencies.to_offset(interval).freqstr)
    if len(intervals) != 1 or (interval is None and any("bar_interval" not in f.attrs for f in frames)):
        raise ValueError("combine_prices requires one shared bar interval")
    result = with_schedule(pd.concat(frames), intervals.pop())
    expected = {tuple(pair) for pair in json.loads(result.attrs["expected_bars"])}
    for frame in frames:
        expected.update(tuple(pair) for pair in json.loads(frame.attrs.get("expected_bars", "[]")))
    result.attrs["expected_bars"] = json.dumps(sorted(expected), separators=(",", ":"))
    if any("price_basis" in f.attrs for f in frames):
        result.attrs["price_basis"] = bases.pop()
    return result
