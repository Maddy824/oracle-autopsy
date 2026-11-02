"""Reference cash and signed-share accounting for already executed fills."""

from collections import defaultdict
from collections.abc import Iterable

import pandas as pd

from autopsy.data.corporate import apply_share_actions
from autopsy.types import Fill, _validate_start_cash, _validated_prices


def replay(
    fills: Iterable[Fill], prices: pd.DataFrame, start_cash: float,
) -> pd.DataFrame:
    """Apply fills at their exact bars and mark holdings at each bar's close.

    Each distinct timestamp produces one account snapshot across all symbols.
    A missing symbol bar uses its last observed close, never a future price.
    Every fill must match a symbol/time bar; duplicates and unmatched fills
    are errors. Fill order within a bar is preserved. Cash includes short-sale
    proceeds and fees; this is accounting cash, not settled buying power.
    Execution timing, settlement and position limits belong to the engine.
    """
    _validate_start_cash(start_cash)
    prices = _validated_prices(prices).sort_index(kind="stable")
    bar_keys = set(zip(prices.index, prices.symbol))
    fills_by_time: dict[pd.Timestamp, list[Fill]] = defaultdict(list)
    for fill in fills:
        if (fill.time, fill.symbol) not in bar_keys:
            raise ValueError(f"fill has no matching symbol/time bar: {fill.symbol} at {fill.time}")
        fills_by_time[fill.time].append(fill)

    cash = float(start_cash)
    positions: dict[str, int] = {}
    last_close: dict[str, float] = {}
    rows = []
    for time, bars in prices.groupby(level=0, sort=True):
        apply_share_actions(positions, bars)
        last_close.update(zip(bars.symbol, bars.close))
        for fill in fills_by_time.get(time, ()):
            signed_qty = fill.qty if fill.side == "BUY" else -fill.qty
            cash -= signed_qty * fill.price + fill.fee
            positions[fill.symbol] = positions.get(fill.symbol, 0) + signed_qty
        holdings_value = sum(qty * last_close[symbol] for symbol, qty in positions.items())
        rows.append((cash, holdings_value, cash + holdings_value, positions.copy()))

    return pd.DataFrame(
        rows, index=prices.index.unique(),
        columns=["cash", "holdings_value", "equity", "positions"],
    ).astype({"cash": float, "holdings_value": float, "equity": float})
