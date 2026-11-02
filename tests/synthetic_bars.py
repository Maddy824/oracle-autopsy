"""Tiny deterministic fixtures; the production synthetic loader belongs to Task 9."""

import json

import numpy as np
import pandas as pd


def five_minute_bars(days=60, symbols=("ALPHA",), seed=6):
    rng = np.random.default_rng(seed)
    sessions = pd.bdate_range("2025-01-01", periods=days, tz="Asia/Kolkata")
    times = pd.DatetimeIndex([
        day + pd.Timedelta(hours=9, minutes=15 + 5 * bar)
        for day in sessions for bar in range(75)
    ])
    frames = []
    for i, symbol in enumerate(symbols):
        opens = (100 + 50 * i) * np.exp(np.cumsum(rng.normal(0, .002, len(times))))
        closes = opens * np.exp(rng.normal(0, .001, len(times)))
        frames.append(pd.DataFrame({
            "symbol": symbol, "open": opens,
            "high": np.maximum(opens, closes) * 1.001,
            "low": np.minimum(opens, closes) * .999,
            "close": closes, "volume": rng.integers(100, 1000, len(times)),
        }, index=times))
    return pd.concat(frames).sort_index(kind="stable")


def _with_schedule(frame):
    # Independent expected schedule survives row drops, including entire sessions.
    # pandas deep-copies attrs for every group: immutable JSON avoids quadratic
    # copying of a large nested list through engine/ledger per-bar operations.
    frame.attrs["expected_bars"] = json.dumps([(time.isoformat(), symbol)
                                             for time, symbol in zip(frame.index, frame.symbol)])
    return frame


def opening_range_bars(days=40, seed=41):
    """Invented, alternating-direction ORB edge, with a flat initial range.

    Each day's random direction is revealed by its breakout, then continues.
    Random entry cannot know that direction; the continuation survives costs.
    """
    bars = five_minute_bars(days=days, seed=seed)
    rng = np.random.default_rng(seed)
    prices = []
    for _ in range(days):
        direction = rng.choice([-1, 1])
        move = rng.uniform(.035, .055)
        path = 100 * (1 + direction * move * np.clip((np.arange(75) - 5) / 67, 0, 1))
        prices.extend(path)
    bars["open"] = prices
    bars["close"] = prices
    bars["high"] = bars.open * 1.0001
    bars["low"] = bars.open * .9999
    return _with_schedule(bars)


def random_walk_bars(days=40, seed=17):
    """Pure additive random walk: zero-drift independent Gaussian increments."""
    bars = five_minute_bars(days=days, seed=seed)
    values = 100 + np.cumsum(np.random.default_rng(seed).normal(0, .04, len(bars)))
    bars["open"] = values
    bars["close"] = values
    bars["high"] = values
    bars["low"] = values
    return _with_schedule(bars)
