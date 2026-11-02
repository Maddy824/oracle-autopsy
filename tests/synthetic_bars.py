"""Tiny deterministic fixtures; the production synthetic loader belongs to Task 9."""

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
