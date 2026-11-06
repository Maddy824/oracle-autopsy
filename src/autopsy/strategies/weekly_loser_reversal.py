"""Pre-registered prior-week losers, observed after each daily close."""

import numpy as np
import pandas as pd

from autopsy.checks import CheckResult
from autopsy.engine import Signal
from autopsy.strategies.earnings_reaction import _index
from autopsy.strategies.events import _opens
from autopsy.strategies.intraday import _check_features, _per_symbol

VARIANTS = {"h5": 4, "h10": 9}


def data_check(prices):
    reason = None
    if prices.attrs.get("bar_interval") not in ("D", "1D", "day", "1d") or any(
        bars.index.normalize().has_duplicates for _, bars in prices.groupby("symbol")
    ):
        reason = "weekly_loser_reversal requires one completed daily bar per symbol/session"
    else:
        index = _index(prices)
        if index.empty or index.index.has_duplicates or not np.isfinite(index).all() or (index <= 0).any():
            reason = "index symbol missing or invalid; supply --index-symbol with daily Nifty prices"
        elif not prices.index.normalize().isin(index.index).all():
            reason = "index prices missing trading sessions"
    return CheckResult("weekly_loser_data", "CAN'T TELL" if reason else "PASS",
                       {"reason": reason} if reason else {})


def features(prices, params):
    VARIANTS[params["variant"]]
    # The independent schedule and index preserve sessions absent from stocks.
    days = sorted(set(_opens(prices)) | set(_index(prices).index))
    sessions = pd.Series(np.arange(len(days)), index=pd.DatetimeIndex(days))

    def calculate(bars):
        previous = bars.close.shift(1)
        tr = pd.concat([bars.high - bars.low, (bars.high - previous).abs(),
                        (bars.low - previous).abs()], axis=1).max(axis=1).where(previous.notna())
        atr = tr.rolling(20, min_periods=20).mean()
        values = bars[["open", "high", "low", "close", "volume"]]
        valid = (np.isfinite(values) & (values > 0)).all(axis=1)
        session = pd.Series(sessions.reindex(bars.index.normalize()).to_numpy(), index=bars.index)
        history = (valid.rolling(21, min_periods=21).sum().eq(21)
                   & session.diff(20).eq(20) & np.isfinite(atr) & (atr > 0))
        return pd.DataFrame({"r5": bars.close / bars.close.shift(5) - 1,
                             "atr20": atr, "history_eligible": history}, index=bars.index)

    result = _per_symbol(prices, calculate)
    result["history_eligible"] &= result.symbol != prices.attrs.get("index_symbol")
    # Work with row positions so simultaneous symbols retain the input order.
    ranked = result.reset_index(drop=True)
    ranked["day"] = result.index.normalize()
    ranked = ranked.loc[ranked.history_eligible].sort_values(["day", "r5", "symbol"])
    groups = ranked.groupby("day", sort=False)
    selected = ranked.loc[(groups.cumcount() < groups.symbol.transform("size") // 5) & (ranked.r5 < 0)]
    result["eligible"] = np.isin(np.arange(len(result)), selected.index)
    return result


def signals(prices, features, params):
    _check_features(prices, features)
    hold = VARIANTS[params["variant"]]
    return sorted((Signal(row.Index, row.symbol, 1, priority=-float(row.r5),
                          risk_distance=2 * float(row.atr20), holding_sessions=hold)
                   for row in features.itertuples() if row.eligible),
                  key=lambda signal: (signal.time, -signal.priority, signal.symbol))
