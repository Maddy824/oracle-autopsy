"""Five-minute, open-stamped IST candles, with HLCV available five minutes later.

Signals describe targets; the engine executes on its next bar and enforces the
15:15/short-session close. No new target is issued at or after 15:15. ORB,
momentum and gap take at most one entry per symbol/session and hold to that
close. VWAP may re-enter after reverting. All statistics reset each session.
"""

import numpy as np
import pandas as pd

from autopsy.engine import Signal
from autopsy.types import _validated_prices


def _per_symbol(prices, calculate):
    """Preserve row order, including simultaneous timestamps across symbols."""
    prices = _validated_prices(prices)
    if not prices.index.is_monotonic_increasing:
        raise ValueError("prices must be ordered by timestamp")
    parts = []
    for symbol, positions in prices.groupby("symbol", sort=False).indices.items():
        part = calculate(prices.iloc[positions])
        part.insert(0, "symbol", symbol)
        part.index = positions
        parts.append(part)
    if not parts:
        return pd.DataFrame({"symbol": pd.Series(dtype=str)}, index=prices.index)
    result = pd.concat(parts).sort_index()
    result.index = prices.index
    return result


def _session(bars):
    day = bars.index.normalize()
    minute = bars.index.hour * 60 + bars.index.minute - (9 * 60 + 15)
    if ((minute < 0) | (minute >= 375) | (minute % 5 != 0)).any() or (
        (bars.index.second != 0) | (bars.index.microsecond != 0) | (bars.index.nanosecond != 0)
    ).any():
        raise ValueError("intraday bars must be five-minute IST bars from 09:15 to 15:25")
    return day, minute


def _completed(bars, day):
    return bars.close.groupby(day).shift(1)


def _range(bars, minutes):
    day, minute = _session(bars)
    inside = pd.Series(minute < minutes, index=bars.index)
    count = inside.groupby(day).cumsum().groupby(day).shift(1)
    ready = (minute >= minutes) & (count == minutes // 5)
    high = bars.high.where(inside).groupby(day).cummax().groupby(day).ffill().groupby(day).shift(1)
    low = bars.low.where(inside).groupby(day).cummin().groupby(day).ffill().groupby(day).shift(1)
    return pd.DataFrame({
        "close": _completed(bars, day),
        "range_high": high.where(ready), "range_low": low.where(ready),
    }, index=bars.index)


def orb_features(prices, params):
    return _per_symbol(prices, lambda bars: _range(bars, params["minutes"]))


def _check_features(prices, features):
    if not prices.index.equals(features.index) or not np.array_equal(prices.symbol, features.symbol):
        raise ValueError("features must align with prices by time and symbol")


def _signals(prices, features, decide, *, once=True):
    _check_features(prices, features)
    states = {}
    result = []
    for row in features.itertuples():
        time = row.Index
        if not (9 * 60 + 15 <= time.hour * 60 + time.minute < 15 * 60 + 15):
            continue
        key = (row.symbol, time.normalize())
        current = states.get(key, 0)
        if once and current:
            continue
        target = decide(row, current)
        if target != current:
            result.append(Signal(time, row.symbol, target))
            states[key] = target
    return result


def orb_signals(prices, features, params):
    """First completed close strictly outside the 15/30-minute high/low; hold."""
    return _signals(prices, features, lambda row, _: (
        1 if row.close > row.range_high else -1 if row.close < row.range_low else 0
    ))


def vwap_features(prices, params):
    """Volume-weighted typical-price mean and population sigma, completed bars."""
    def calculate(bars):
        day, _ = _session(bars)
        typical = (bars.high + bars.low + bars.close) / 3
        volume = bars.volume.groupby(day).cumsum().replace(0, np.nan)
        mean = (typical * bars.volume).groupby(day).cumsum() / volume
        second = (typical ** 2 * bars.volume).groupby(day).cumsum() / volume
        return pd.DataFrame({
            "close": _completed(bars, day), "vwap": mean.groupby(day).shift(1),
            "sigma": (second - mean ** 2).clip(lower=0).pow(.5).groupby(day).shift(1),
        }, index=bars.index)
    return _per_symbol(prices, calculate)


def vwap_signals(prices, features, params):
    """Fade close at >= deviation sigma from VWAP; exit on crossing VWAP."""
    def decide(row, current):
        if current:
            return 0 if current * (row.close - row.vwap) >= 0 else current
        if row.sigma > 0:
            if row.close <= row.vwap - params["deviation"] * row.sigma:
                return 1
            if row.close >= row.vwap + params["deviation"] * row.sigma:
                return -1
        return 0
    return _signals(prices, features, decide, once=False)


def momentum_features(prices, params):
    def calculate(bars):
        day, minute = _session(bars)
        opening = bars.open.where(minute == 0).groupby(day).ffill()
        first_hour_close = bars.close.where(minute == 55).groupby(day).ffill().groupby(day).shift(1)
        complete = _range(bars, 60).range_high.notna()
        return ((first_hour_close - opening) / opening * 100).where(complete).to_frame("hour_return")
    return _per_symbol(prices, calculate)


def momentum_signals(prices, features, params):
    """After 10:15, follow the frozen 09:15-open to 10:10-close return >= threshold%."""
    def decide(row, _):
        if row.Index.hour * 60 + row.Index.minute <= 10 * 60 + 15:
            return 0
        if abs(row.hour_return) >= params["threshold"]:
            return 1 if row.hour_return > 0 else -1
        return 0
    return _signals(prices, features, decide)


def gap_features(prices, params):
    def calculate(bars):
        day, _ = _session(bars)
        # Yesterday's last close is known at today's first open. Never broadcast
        # today's final close into today's rows.
        previous_close = bars.close.groupby(day).last().shift(1).reindex(day)
        previous_close.index = bars.index
        opening = bars.open.groupby(day).transform("first")
        return pd.DataFrame({
            "gap_pct": (opening - previous_close) / previous_close * 100,
            "first_bar": ~day.duplicated(),
        }, index=bars.index)
    return _per_symbol(prices, calculate)


def gap_signals(prices, features, params):
    """At the first open, fade/follow a gap >= gap% versus prior session close; hold."""
    def decide(row, _):
        if row.first_bar and abs(row.gap_pct) >= params["gap"]:
            direction = 1 if row.gap_pct > 0 else -1
            return direction if params["mode"] == "continue" else -direction
        return 0
    return _signals(prices, features, decide)
