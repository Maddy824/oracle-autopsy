"""Pre-registered daily, completed-bar earnings reaction (four trials).

D is the first scheduled open strictly after dissemination, without a minute
delay. Daily row timestamps label sessions: features at D mean *after D closes*,
and orders execute at the next row's open. Date-only rows use 09:15 IST for
event eligibility; explicitly timed schedules retain their session opens.
ATR20 is the simple mean of 20 true ranges through D (each needs prior close).
"""

import json

import numpy as np
import pandas as pd

from autopsy.checks import CheckResult
from autopsy.engine import Signal
from autopsy.news.events import events_from_prices
from autopsy.strategies.events import _opens
from autopsy.strategies.intraday import _check_features, _per_symbol

VARIANTS = {"h10_regime": (10, True), "h5_regime": (5, True),
            "h20_regime": (20, True), "h10_noregime": (10, False)}


def attach_index(prices, symbol):
    """Freeze index context as JSON, excluding it from the trading universe.

    Historical index rows warm SMA200 even in a sealed holdout. Consumers
    restrict context to the current prefix before calculating any features.
    The index identity and observations participate in the research hash.
    """
    index = prices.loc[prices.symbol == symbol]
    if index.empty:
        raise ValueError("index symbol missing from prices")
    result = prices.loc[prices.symbol != symbol].copy()
    result.attrs["index_symbol"] = symbol
    result.attrs["index_prices"] = json.dumps(
        [[time.isoformat(), float(close)] for time, close in index.close.items()],
        separators=(",", ":"), allow_nan=False)
    schedule = prices.attrs.get("expected_bars")
    if schedule is not None:
        schedule = json.loads(schedule) if isinstance(schedule, str) else schedule
        result.attrs["expected_bars"] = json.dumps([pair for pair in schedule if pair[1] != symbol])
    return result


def _index(prices):
    symbol = prices.attrs.get("index_symbol")
    if not symbol or prices.empty:
        return pd.Series(dtype=float)
    if "index_prices" in prices.attrs:
        rows = json.loads(prices.attrs["index_prices"])
        rows = [row for row in rows if pd.Timestamp(row[0]).normalize() <= prices.index.max().normalize()]
        if not rows:
            return pd.Series(dtype=float)
        series = pd.Series([row[1] for row in rows],
                           index=pd.DatetimeIndex([row[0] for row in rows]), dtype=float)
    else:
        series = prices.loc[prices.symbol == symbol, "close"].copy()
    if series.empty or prices.empty:
        return pd.Series(dtype=float)
    series.index = series.index.tz_convert("Asia/Kolkata").normalize()
    return series.loc[series.index <= prices.index.max().normalize()].sort_index()


def _symbol(event, symbols):
    # NSE exports use bare tickers; Kite uses EXCHANGE:TRADINGSYMBOL.
    if event.symbol in symbols:
        return event.symbol
    qualified = "NSE:" + event.symbol
    return qualified if qualified in symbols and event.source == "NSE" else None


def event_sessions(prices):
    """Return (tradable symbol, D) pairs, independent of reaction/regime."""
    opens = {day: (time if time != day else day + pd.Timedelta(hours=9, minutes=15))
             for day, time in _opens(prices).items()}
    symbols = set(prices.symbol) - {prices.attrs.get("index_symbol")}
    result = set()
    for event in events_from_prices(prices):
        symbol = _symbol(event, symbols)
        if symbol is None or event.kind != "results" or event.disseminated_at is None:
            continue
        day = next((day for day, opening in opens.items() if opening > event.disseminated_at), None)
        if day is not None:
            result.add((symbol, day))
    return result


def data_check(prices):
    reason = None
    interval = prices.attrs.get("bar_interval")
    if interval not in ("D", "1D", "day", "1d") or any(
        bars.index.normalize().has_duplicates for _, bars in prices.groupby("symbol")
    ):
        reason = "earnings_reaction requires one completed daily bar per symbol/session"
    else:
        index = _index(prices)
        if index.empty or index.index.has_duplicates or not np.isfinite(index).all() or (index <= 0).any():
            reason = "index symbol missing or invalid; supply --index-symbol with daily Nifty prices"
        elif not prices.index.normalize().isin(index.index).all():
            reason = "index prices missing trading sessions"
        elif not any(day in prices.index.normalize() for _, day in event_sessions(prices)):
            reason = "no results events with dissemination time and an eligible session attached"
    return CheckResult("event_data", "CAN'T TELL" if reason else "PASS",
                       {"reason": reason} if reason else {})


def features(prices, params):
    _, regime = VARIANTS[params["variant"]]
    index = _index(prices)
    index_return = index / index.shift(1) - 1
    index_sma = index.rolling(200, min_periods=200).mean()

    def calculate(bars):
        previous = bars.close.shift(1)
        tr = pd.concat([bars.high - bars.low, (bars.high - previous).abs(),
                        (bars.low - previous).abs()], axis=1).max(axis=1).where(previous.notna())
        days = bars.index.normalize()
        market = index_return.reindex(days).to_numpy()
        regime_ok = (index > index_sma).reindex(days, fill_value=False).to_numpy()
        excess = bars.close / previous - 1 - market
        atr = tr.rolling(20, min_periods=20).mean()
        return pd.DataFrame({"excess": excess, "atr20": atr,
                             "reaction": (bars.close > previous) & (excess > 0),
                             "regime": regime_ok}, index=bars.index)

    result = _per_symbol(prices, calculate)
    sessions = event_sessions(prices)
    result["event"] = [(symbol, time.normalize()) in sessions
                       for time, symbol in zip(result.index, result.symbol)]
    result["eligible"] = (result.event & result.reaction & (result.atr20 > 0)
                          & (result.regime if regime else True))
    return result


def signals(prices, features, params):
    _check_features(prices, features)
    hold, _ = VARIANTS[params["variant"]]
    # The engine owns position state: a rejected entry must not create a
    # phantom holding or a stop based on an unexecuted theoretical price.
    return sorted((Signal(row.Index, row.symbol, 1, priority=float(row.excess),
                          risk_distance=2 * float(row.atr20), holding_sessions=hold)
                   for row in features.itertuples() if row.eligible),
                  key=lambda signal: (signal.time, -signal.priority, signal.symbol))
