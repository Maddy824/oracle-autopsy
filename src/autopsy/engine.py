"""Whole-share, next-bar simulation with entry budgets and delivery settlement."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from math import floor, isfinite
from numbers import Integral
from typing import Literal

import numpy as np
import pandas as pd

from autopsy.calendar import _intraday_closes
from autopsy.costs import RateTable, trade_costs
from autopsy.data.corporate import apply_share_actions
from autopsy.types import Fill, RunRecord, _TIMEZONE, _validate_start_cash, _validated_prices


@dataclass(frozen=True)
class Signal:
    """A desired direction, observed at time (never executable at that time).

    Optional managed swing entries rank by descending priority, size with a
    fixed per-share risk_distance and exit on a close-based stop/holding limit.
    Daily strategy timestamps label completed sessions, not intraday signals.
    """

    time: pd.Timestamp
    symbol: str
    target: Literal[-1, 0, 1]
    priority: float = 0.0
    risk_distance: float | None = None
    holding_sessions: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.time, pd.Timestamp) or pd.isna(self.time) or self.time.tz is None:
            raise ValueError("time must be a valid tz-aware pd.Timestamp")
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be a nonempty string")
        if isinstance(self.target, bool) or not isinstance(self.target, Integral) or self.target not in (-1, 0, 1):
            raise ValueError("target must be -1, 0 or 1")
        object.__setattr__(self, "time", self.time.tz_convert(_TIMEZONE))
        object.__setattr__(self, "target", int(self.target))
        if not isfinite(self.priority):
            raise ValueError("priority must be finite")
        if self.risk_distance is not None and (not isfinite(self.risk_distance) or self.risk_distance <= 0):
            raise ValueError("risk_distance must be finite and positive")
        if self.holding_sessions is not None and (
            isinstance(self.holding_sessions, bool) or not isinstance(self.holding_sessions, Integral)
            or self.holding_sessions < 1
        ):
            raise ValueError("holding_sessions must be a positive integer")
        if (self.risk_distance is None) != (self.holding_sessions is None) or (
            self.risk_distance is not None and self.target != 1
        ):
            raise ValueError("managed long entries require both risk_distance and holding_sessions")


def run_backtest(
    prices: pd.DataFrame,
    signals: Iterable[Signal],
    mode: Literal["intraday", "swing"],
    capital: float = 200_000,
    *,
    slippage_bps: float,
    rates: RateTable,
) -> RunRecord:
    """Execute targets at the next available bar of their own symbol.

    Entry notional plus entry fees must fit settled cash and the fixed initial
    capital allocation (100% intraday, 20% swing). Short entries reserve the
    same budget as longs; short proceeds cannot fund another position. Losses
    can reduce buying power; market gaps can still cause negative equity.

    Managed swing entries instead use floor(min(20% * equity / slipped price,
    0.25% * equity / risk_distance)), further limited by settled cash including
    fees. Equity is marked at available opens after exits and before this batch
    of entries. Their stop is actual slipped fill minus risk_distance, fixed
    until a share action rescales it. Only completed closes trigger the stop;
    gaps execute at the next available open with adverse slippage.

    Targets do not rebalance existing positions. At a shared execution time,
    exits precede entries, then entries sort by signal time, descending priority
    and symbol. The
    latest signal wins if several reach the same symbol/bar; duplicate signal
    times for one symbol are rejected. Unaffordable or capacity-blocked entries
    are ignored, not queued. Intraday signals expire at the session boundary.

    Delivery sale proceeds enter accounting cash immediately but become buying
    power only on the next observed trading day (T+1). Swing holdings remain
    open at the end of the data. Reported equity is marked independently of
    the reference replay ledger, at each distinct timestamp's close.
    """
    if mode not in ("intraday", "swing"):
        raise ValueError("mode must be intraday or swing")
    _validate_start_cash(capital)
    if isinstance(slippage_bps, bool) or not isfinite(slippage_bps) or not 0 <= slippage_bps < 10_000:
        raise ValueError("slippage_bps must be finite and in [0, 10000)")
    if not isinstance(rates, RateTable):
        raise ValueError("rates must be a verified RateTable")
    prices = _validated_prices(prices).sort_index(kind="stable")
    if not np.isfinite(prices.open).all() or (prices.open <= 0).any():
        raise ValueError("open prices must be finite and positive")

    signals = list(signals)
    if any(not isinstance(signal, Signal) for signal in signals):
        raise ValueError("signals must contain Signal records")
    if mode == "swing" and any(signal.target == -1 for signal in signals):
        raise ValueError("swing signals must be long only")
    if mode != "swing" and any(signal.risk_distance is not None for signal in signals):
        raise ValueError("managed entries require swing mode")
    symbol_times = {symbol: bars.index for symbol, bars in prices.groupby("symbol")}
    pending: dict[pd.Timestamp, dict[str, Signal]] = defaultdict(dict)
    seen = set()
    for signal in sorted(signals, key=lambda s: (s.time, s.symbol)):
        key = (signal.time, signal.symbol)
        if key in seen:
            raise ValueError("duplicate symbol/time signal")
        seen.add(key)
        if signal.symbol not in symbol_times:
            raise ValueError(f"signal has unknown symbol: {signal.symbol}")
        times = symbol_times[signal.symbol]
        next_index = times.searchsorted(signal.time, side="right")
        if next_index == len(times):
            continue
        execution_time = times[next_index]
        if mode == "intraday" and execution_time.normalize() != signal.time.normalize():
            continue
        pending[execution_time][signal.symbol] = signal

    cutoff = _intraday_closes(prices) if mode == "intraday" else {}
    segment = "intraday_equity" if mode == "intraday" else "delivery_equity"
    allocation = float(capital) * (1.0 if mode == "intraday" else 0.2)
    fills: list[Fill] = []
    positions: dict[str, int] = {}
    last_close: dict[str, float] = {}
    sold_today: set[str] = set()
    cash = float(capital)
    unsettled = 0.0
    current_day = None
    equity = []
    managed = {}

    def fee_for(symbol: str, side: str, qty: int, price: float) -> float:
        return trade_costs(
            side, qty * price, segment, rates,
            symbol_sold_today=symbol in sold_today,
        ).total

    def execution_price(symbol: str, side: str) -> float:
        return float(opens[symbol]) * (1 + (1 if side == "BUY" else -1) * slippage_bps / 10_000)

    def execute(symbol: str, side: str, qty: int) -> None:
        nonlocal cash, unsettled
        price = execution_price(symbol, side)
        fee = fee_for(symbol, side, qty, price)
        fills.append(Fill(time, symbol, side, qty, price, fee))
        delta = qty if side == "BUY" else -qty
        cash -= delta * price + fee
        positions[symbol] = positions.get(symbol, 0) + delta
        if not positions[symbol]:
            del positions[symbol]
            managed.pop(symbol, None)
        if side == "SELL":
            sold_today.add(symbol)
            if mode == "swing":
                unsettled += max(0.0, qty * price - fee)

    for time, bars in prices.groupby(level=0, sort=True):
        apply_share_actions(positions, bars)
        if "share_multiplier" in bars:
            for row in bars.itertuples():
                if row.symbol in managed:
                    managed[row.symbol]["stop"] /= row.share_multiplier
        day = time.normalize()
        if day != current_day:
            # Every new date in these bars is the next observed trading day.
            unsettled = 0.0
            sold_today.clear()
            current_day = day
        opens = dict(zip(bars.symbol, bars.open))
        orders = sorted(pending.get(time, {}).values(), key=lambda s: (s.time, -s.priority, s.symbol))
        if mode == "intraday":
            for symbol in sorted(positions):
                if time == cutoff[symbol, day]:
                    qty = positions[symbol]
                    execute(symbol, "SELL" if qty > 0 else "BUY", abs(qty))

        # A target change closes the existing position before opening its reverse.
        for signal in orders:
            qty = positions.get(signal.symbol, 0)
            if qty and (1 if qty > 0 else -1) != signal.target:
                execute(signal.symbol, "SELL" if qty > 0 else "BUY", abs(qty))

        # Mark existing holdings at available opens, never this bar's close.
        entry_equity = cash + sum(qty * opens.get(symbol, last_close.get(symbol, 0))
                                  for symbol, qty in positions.items())
        for signal in orders:
            symbol = signal.symbol
            if not signal.target or symbol in positions:
                continue
            if mode == "intraday" and time >= cutoff[symbol, day]:
                continue
            if len(positions) >= (1 if mode == "intraday" else 5):
                continue
            budget = cash - unsettled if signal.risk_distance is not None else min(allocation, cash - unsettled)
            if budget <= 0:
                continue
            side = "BUY" if signal.target == 1 else "SELL"
            price = execution_price(symbol, side)
            # Costs are monotone in quantity; binary search includes capped fees
            # without a slow share-by-share decrement for low-priced stocks.
            low, high = 0, floor(budget / price)
            if signal.risk_distance is not None:
                high = min(high, max(0, floor(min(.2 * entry_equity / price,
                                                .0025 * entry_equity / signal.risk_distance))))
            while low < high:
                qty = (low + high + 1) // 2
                if qty * price + fee_for(symbol, side, qty, price) <= budget:
                    low = qty
                else:
                    high = qty - 1
            if low:
                execute(symbol, side, low)
                if signal.risk_distance is not None:
                    managed[symbol] = {"stop": price - signal.risk_distance,
                                       "hold": signal.holding_sessions, "age": 0, "day": day}

        # Completed daily closes schedule exits at the next symbol open. Age
        # matches events._holding_signals: entry day is 0, signal at age N.
        for row in bars.itertuples():
            state = managed.get(row.symbol)
            if state is None:
                continue
            state["age"] += int(day != state["day"])
            state["day"] = day
            if row.close < state["stop"] or state["age"] >= state["hold"]:
                times = symbol_times[row.symbol]
                following = times.searchsorted(time, side="right")
                if following < len(times):
                    pending[times[following]][row.symbol] = Signal(time, row.symbol, 0)

        last_close.update(zip(bars.symbol, bars.close))
        equity.append(cash + sum(qty * last_close[symbol] for symbol, qty in positions.items()))

    record = RunRecord(
        fills,
        pd.Series(equity, index=prices.index.unique(), dtype=float, name="equity"),
        prices,
        float(capital),
    )
    # Statistics must reprice with this exact execution configuration. Plain
    # dictionaries survive pandas attrs copies (RateTable contains proxies).
    record.reported_equity.attrs["autopsy_execution"] = {
        "mode": mode,
        "slippage_bps": float(slippage_bps),
        "rates": {
            "broker": rates.broker, "source_url": rates.source_url,
            "accessed": rates.accessed,
            "segment_rates": {name: dict(values) for name, values in rates.segment_rates.items()},
        },
    }
    return record
