"""Seeded, invented five-minute sessions for offline development only."""

from numbers import Integral

import numpy as np
import pandas as pd

from autopsy.data.schedule import with_schedule


def synthetic_intraday(days, seed, pattern="random_walk", sigma=.0004):
    """Return 75 bars/day, 09:15–15:25 IST, with an expected session grid.

    sigma is the random walk's per-bar volatility; bar wicks are sigma / 4.
    About .0017 resembles a liquid Nifty 50 stock (roughly 1.5% a day).

    Weekdays from 2025-01-01 are synthetic sessions, not an NSE calendar.
    planted_orb holds its first 30 minutes flat then continues a seeded
    breakout. It is a test edge, never evidence about a real market.
    """
    if isinstance(days, bool) or not isinstance(days, Integral) or days < 1:
        raise ValueError("days must be a positive integer")
    if pattern not in ("random_walk", "flat", "planted_orb"):
        raise ValueError("unknown synthetic pattern")
    rng = np.random.default_rng(seed)
    sessions = pd.bdate_range("2025-01-01", periods=days, tz="Asia/Kolkata")
    times = pd.DatetimeIndex([day + pd.Timedelta(minutes=555 + 5 * bar)
                              for day in sessions for bar in range(75)], name="time")
    values = np.full(len(times), 100.)
    if pattern == "random_walk":
        values *= np.exp(np.cumsum(rng.normal(-.5 * sigma ** 2, sigma, len(times))))
    elif pattern == "planted_orb":
        values = np.concatenate([100 * (1 + rng.choice([-1, 1]) * rng.uniform(.035, .055)
                                        * np.clip((np.arange(75) - 5) / 67, 0, 1))
                                 for _ in sessions])
    frame = pd.DataFrame({"symbol": "SYNTH", "open": values, "high": values * (1 + sigma / 4),
                          "low": values * (1 - sigma / 4), "close": values,
                          "volume": rng.integers(1000, 5000, len(times))}, index=times)
    frame.attrs["source"] = "synthetic"
    return with_schedule(frame, "5min")
