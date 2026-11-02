"""Shared records and validation for timestamped, whole-share accounting."""

from dataclasses import dataclass
from math import isfinite
from numbers import Integral
from typing import Literal

import numpy as np
import pandas as pd


_TIMEZONE = "Asia/Kolkata"
_PRICE_COLUMNS = {"symbol", "open", "high", "low", "close", "volume"}


def _ist_index(index: pd.Index, name: str) -> pd.DatetimeIndex:
    if not isinstance(index, pd.DatetimeIndex) or index.tz is None or index.hasnans:
        raise ValueError(f"{name} index must contain valid tz-aware timestamps")
    return index.tz_convert(_TIMEZONE)


def _validate_start_cash(start_cash: float) -> None:
    if not isfinite(start_cash) or start_cash < 0:
        raise ValueError("start_cash must be finite and nonnegative")


def _validated_prices(prices: pd.DataFrame) -> pd.DataFrame:
    index = _ist_index(prices.index, "prices")
    missing = _PRICE_COLUMNS - set(prices.columns)
    if missing:
        raise ValueError(f"prices missing columns: {', '.join(sorted(missing))}")
    if not prices.columns.is_unique:
        raise ValueError("prices must have unique columns")
    if not prices.symbol.map(lambda value: isinstance(value, str) and bool(value.strip())).all():
        raise ValueError("prices symbols must be nonempty strings")
    if not np.isfinite(prices.close).all() or (prices.close <= 0).any():
        raise ValueError("close prices must be finite and positive")
    keys = pd.MultiIndex.from_arrays([index, prices.symbol])
    if keys.has_duplicates:
        raise ValueError("duplicate symbol/time bar")
    result = prices.copy()
    result.index = index
    return result


@dataclass(frozen=True)
class Fill:
    """An executed fill; quantity is a positive integer on either side."""

    time: pd.Timestamp
    symbol: str
    side: Literal["BUY", "SELL"]
    qty: int
    price: float
    fee: float

    def __post_init__(self) -> None:
        if not isinstance(self.time, pd.Timestamp) or pd.isna(self.time) or self.time.tz is None:
            raise ValueError("time must be a valid tz-aware pd.Timestamp")
        if isinstance(self.qty, bool) or not isinstance(self.qty, Integral) or self.qty <= 0:
            raise ValueError("qty must be a positive whole-share integer")
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be a nonempty string")
        if self.side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if not isfinite(self.price) or self.price <= 0:
            raise ValueError("price must be finite and positive")
        if not isfinite(self.fee) or self.fee < 0:
            raise ValueError("fee must be finite and nonnegative")
        object.__setattr__(self, "time", self.time.tz_convert(_TIMEZONE))
        object.__setattr__(self, "qty", int(self.qty))


@dataclass
class RunRecord:
    """Executed fills, reported equity and the prices used to audit a run."""

    fills: list[Fill]
    reported_equity: pd.Series
    prices: pd.DataFrame
    start_cash: float

    def __post_init__(self) -> None:
        _validate_start_cash(self.start_cash)
        self.prices = _validated_prices(self.prices)
        index = _ist_index(self.reported_equity.index, "reported_equity")
        self.reported_equity = self.reported_equity.copy()
        self.reported_equity.index = index
