"""Explicit split/bonus factors for signals and raw-price accounting.

actions is a DataFrame with symbol, time (aware effective timestamp), kind
('split' or 'bonus'), ratio. Split ratio means new shares per old share (2
for a 1:2 split); bonus ratio means additional shares per old (.5 for 1:2
bonus). with_actions returns RAW prices with share_multiplier on the first
symbol bar at/after the effective timestamp. Pass those raw prices to the
engine/ledger; use adjust(raw, actions) only for strategy signals. Historical
OHLC is divided by subsequent multipliers, volume multiplied. Cash is never
changed by an action. Fractional entitlements require cash-in-lieu data and
are rejected by accounting instead of silently rounded.
"""

from math import isclose, isfinite

import pandas as pd

from autopsy.types import _validated_prices


def with_actions(raw, actions):
    frame = _validated_prices(raw).sort_index(kind="stable")
    if frame.attrs.get("price_basis") == "adjusted":
        raise ValueError("corporate actions require raw, not adjusted prices")
    if not {"symbol", "time", "kind", "ratio"} <= set(actions):
        raise ValueError("actions require symbol, time, kind, ratio")
    frame["share_multiplier"] = 1.
    seen = set()
    for action in actions.to_dict("records"):
        time = pd.Timestamp(action["time"])
        if pd.isna(time) or time.tz is None:
            raise ValueError("action time must be tz-aware")
        time = time.tz_convert("Asia/Kolkata")
        symbol, kind = action["symbol"], action["kind"]
        ratio = float(action["ratio"])
        if kind not in ("split", "bonus") or not isfinite(ratio) or ratio <= 0:
            raise ValueError("action requires split/bonus and a positive finite ratio")
        key = (symbol, time, kind)
        if key in seen:
            raise ValueError("duplicate corporate action")
        seen.add(key)
        bars = frame[frame.symbol == symbol]
        if bars.empty:
            raise ValueError(f"action symbol absent from prices: {symbol}")
        applicable = bars.index[bars.index >= time]
        # An action before this history is already reflected in every raw bar.
        if len(applicable) and time > bars.index[0]:
            mask = (frame.symbol == symbol) & (frame.index == applicable[0])
            frame.loc[mask, "share_multiplier"] *= ratio if kind == "split" else 1 + ratio
    frame.attrs["price_basis"] = "raw"
    return frame


def adjust(raw, actions):
    frame = with_actions(raw, actions)
    for _, bars in frame.groupby("symbol", sort=False):
        factors = bars.share_multiplier.iloc[::-1].cumprod().iloc[::-1] / bars.share_multiplier
        mask = frame.symbol == bars.symbol.iloc[0]
        frame.loc[mask, ["open", "high", "low", "close"]] = (
            bars[["open", "high", "low", "close"]].astype(float).div(factors, axis=0).to_numpy())
        frame.loc[mask, "volume"] = bars.volume.to_numpy() * factors.to_numpy()
    frame = frame.drop(columns="share_multiplier")
    frame.attrs["price_basis"] = "adjusted"
    return frame


def apply_share_actions(positions, bars):
    """Apply today's effective factors BEFORE fills, in place, with no cash flow."""
    if "share_multiplier" not in bars:
        return
    for symbol, factor in zip(bars.symbol, bars.share_multiplier):
        if not isfinite(factor) or factor <= 0:
            raise ValueError("share_multiplier must be positive and finite")
        if symbol in positions:
            shares = positions[symbol] * factor
            if not isclose(shares, round(shares), rel_tol=0, abs_tol=1e-9):
                raise ValueError("corporate action requires whole-share entitlement; cash-in-lieu unavailable")
            positions[symbol] = round(shares)
