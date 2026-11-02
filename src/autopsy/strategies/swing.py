"""Long-only rules, evaluated once per observed session from completed sessions.

Daily candles (even midnight-labelled ones) become available on the next
observed session. Five-minute input is aggregated per symbol/session with the
same one-session lag. A partial current session can never revise its own
features. Signals at that session's first timestamp execute on the engine's
next bar. Holding limits count observed sessions, never individual candles.
"""

import pandas as pd

from autopsy.engine import Signal
from autopsy.strategies.intraday import _check_features, _per_symbol


def _daily_features(prices, calculate):
    def per_symbol(bars):
        days = bars.index.normalize()
        daily = bars.groupby(days).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
        observed = calculate(daily).shift(1).reindex(days)
        observed.index = bars.index
        return observed
    return _per_symbol(prices, per_symbol)


def breakout_features(prices, params):
    def calculate(daily):
        return pd.DataFrame({
            "close": daily.close,
            "prior_high": daily.high.shift(1).rolling(params["n"]).max(),
            "prior_low": daily.low.shift(1).rolling(params["n"]).min(),
        })
    return _daily_features(prices, calculate)


def pullback_features(prices, params):
    def calculate(daily):
        ma = daily.close.rolling(params["ma"]).mean()
        peak = daily.high.rolling(20).max()
        return pd.DataFrame({
            "close": daily.close, "ma": ma, "prior_ma": ma.shift(1), "peak": peak,
            "pullback_pct": (peak - daily.close) / peak * 100,
        })
    return _daily_features(prices, calculate)


def reversal_features(prices, params):
    return _daily_features(prices, lambda daily: pd.DataFrame({
        "return_pct": (daily.close - daily.close.shift(params["lookback"])) / daily.close.shift(params["lookback"]) * 100,
    }))


def _signals(prices, features, enter, leave, max_hold):
    _check_features(prices, features)
    states = {}
    seen = set()
    signals = []
    for row in features.itertuples():
        key = (row.symbol, row.Index.normalize())
        if key in seen:
            continue
        seen.add(key)
        state = states.get(row.symbol)
        if state is not None:
            entry, age = state
            age += 1
            if age >= max_hold or leave(row, entry):
                signals.append(Signal(row.Index, row.symbol, 0))
                del states[row.symbol]
            else:
                states[row.symbol] = (entry, age)
        elif enter(row):
            signals.append(Signal(row.Index, row.symbol, 1))
            states[row.symbol] = (row, 0)
    return signals


def breakout_signals(prices, features, params):
    """Buy close > preceding N-session high; exit below N-session low or after 20 sessions."""
    return _signals(prices, features,
                    lambda row: row.close > row.prior_high,
                    lambda row, _: row.close < row.prior_low, 20)


def pullback_signals(prices, features, params):
    """Buy >= pullback% below 20-session high above rising MA; exit at entry peak/MA/20 sessions."""
    return _signals(prices, features,
                    lambda row: row.close > row.ma > row.prior_ma and row.pullback_pct >= params["pullback"],
                    lambda row, entry: row.close >= entry.peak or row.close <= row.ma, 20)


def reversal_signals(prices, features, params):
    """Buy negative lookback-session return; exit when nonnegative or after lookback sessions."""
    return _signals(prices, features,
                    lambda row: row.return_pct < 0,
                    lambda row, _: row.return_pct >= 0, params["lookback"])
