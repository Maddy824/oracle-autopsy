"""Three fixed event rules and separately registered intraday filter variants.

All event clocks use dissemination plus 1/5/15 minutes, never first_seen_at.
The first eligible candle emits a Signal; the engine fills on the next bar.
Earnings buys require a verified positive comparable-period earnings change.
Block/bulk buys use the next observed session AFTER the disclosure date (not
the deal date), hold one session, and never infer a buyer before publication.
Earnings holds 1/3/5 observed sessions from the engine's actual entry bar.
Post-results ORB is long only, on the next session, after a completed 15-minute
range and a completed close above it; the engine supplies the intraday exit.
All event rules require open-stamped five-minute bars to resolve minute delays.

The filter freezes at the scheduled session open, using only strictly earlier
notices. scheduled_for overrides the disclosure date for advance notices;
without it only that disclosure date is filtered. Exits are always preserved.
"""

import json

import numpy as np
import pandas as pd

from autopsy.checks import CheckResult
from autopsy.engine import Signal
from autopsy.news.events import events_from_prices
from autopsy.strategies.intraday import _check_features, _per_symbol

DELAYS = (1, 5, 15)


def _opens(prices):
    """Use the loader's schedule so a missing opening candle cannot move open."""
    schedule = prices.attrs.get("expected_bars")
    times = ([pd.Timestamp(pair[0]) for pair in json.loads(schedule)] if isinstance(schedule, str)
             else [pd.Timestamp(pair[0]) for pair in schedule] if schedule is not None
             else prices.index)
    opens = {}
    for time in times:
        day = time.normalize()
        opens[day] = min(time, opens.get(day, time))
    return dict(sorted(opens.items()))


def _check(prices, kinds, *, earnings=False, deals=False, intraday=True):
    if "events" not in prices.attrs:
        return CheckResult("event_data", "CAN'T TELL", {"reason": "event ledger unavailable"})
    if intraday and prices.attrs.get("bar_interval") not in ("5min", "5T"):
        return CheckResult("event_data", "CAN'T TELL", {"reason": "five-minute event bars required"})
    symbols = set(prices.symbol)
    for event in events_from_prices(prices):
        if event.symbol not in symbols or event.kind not in kinds:
            continue
        if event.disseminated_at is None:
            return CheckResult("event_data", "CAN'T TELL", {"reason": "missing dissemination time",
                                                           "symbol": event.symbol, "doc_hash": event.doc_hash})
        if prices.empty or event.disseminated_at > prices.index.max():
            continue
        if earnings and event.earnings_change is None:
            return CheckResult("event_data", "CAN'T TELL", {"reason": "verified earnings change unavailable"})
        if deals and event.side is None:
            return CheckResult("event_data", "CAN'T TELL", {"reason": "disclosed deal side unavailable"})
    return CheckResult("event_data", "PASS", {})


def earnings_data_check(prices):
    return _check(prices, {"results"}, earnings=True)


def results_data_check(prices):
    return _check(prices, {"results"})


def deals_data_check(prices):
    return _check(prices, {"bulk_deal", "block_deal"}, deals=True)


def _event_features(prices, params, family):
    if params["delay"] not in DELAYS or isinstance(params["delay"], bool):
        raise ValueError("event delay must be 1, 5 or 15 minutes")
    result = _per_symbol(prices, lambda bars: pd.DataFrame({"eligible": False}, index=bars.index))
    if prices.attrs.get("bar_interval") not in ("5min", "5T"):
        return result
    opens = _opens(prices)
    days = list(opens)
    allowed = {"bulk_deal", "block_deal"} if family == "deals" else {"results"}
    for event in events_from_prices(prices):
        if event.kind not in allowed or event.disseminated_at is None:
            continue
        if family == "earnings" and (event.earnings_change is None or event.earnings_change <= 0):
            continue
        if family == "deals" and event.side != "BUY":
            continue
        ready = event.disseminated_at + pd.Timedelta(minutes=params["delay"])
        mask = (prices.symbol.to_numpy() == event.symbol) & (prices.index >= ready)
        if family in ("deals", "orb"):
            next_day = next((day for day in days if day > event.disseminated_at.normalize()), None)
            if next_day is None:
                continue
            mask &= prices.index.normalize() == next_day
        indices = np.flatnonzero(mask)
        if len(indices):
            result.iloc[indices if family == "orb" else indices[:1], result.columns.get_loc("eligible")] = True
    return result


def earnings_features(prices, params):
    return _event_features(prices, params, "earnings")


def deals_features(prices, params):
    return _event_features(prices, params, "deals")


def post_results_features(prices, params):
    ready = _event_features(prices, params, "orb")
    opens = _opens(prices)

    def ranges(bars):
        output = pd.DataFrame({"close": np.nan, "range_high": np.nan}, index=bars.index)
        for day, group in bars.groupby(bars.index.normalize()):
            # Completed prices are available independently of range completeness.
            previous = group.close.reindex(group.index - pd.Timedelta(minutes=5)).to_numpy()
            output.loc[group.index, "close"] = previous
            start = opens[day]
            boundary = start + pd.Timedelta(minutes=15)
            needed = pd.date_range(start, periods=3, freq="5min")
            if not needed.isin(group.index).all():
                continue
            high = group.loc[needed, "high"].max()
            # A missing predecessor cannot masquerade as the just-completed bar.
            output.loc[group.index[group.index >= boundary], "range_high"] = high
        return output

    result = _per_symbol(prices, ranges)
    result["eligible"] = ready.eligible.to_numpy()
    return result


def _holding_signals(prices, features, holding_days):
    _check_features(prices, features)
    states, signals = {}, []
    for row in features.itertuples():
        day = row.Index.normalize()
        if row.symbol in states:
            entry_day, age, last_day = states[row.symbol]
            if entry_day is None:
                # This is the next symbol bar, where the engine executes entry.
                states[row.symbol] = (day, 0, day)
            else:
                age += int(day != last_day)
                if age >= holding_days:
                    signals.append(Signal(row.Index, row.symbol, 0))
                    del states[row.symbol]
                else:
                    states[row.symbol] = (entry_day, age, day)
        elif row.eligible:
            signals.append(Signal(row.Index, row.symbol, 1))
            states[row.symbol] = (None, 0, day)
    return signals


def earnings_signals(prices, features, params):
    if params["holding_days"] not in (1, 3, 5) or isinstance(params["holding_days"], bool):
        raise ValueError("holding_days must be 1, 3 or 5")
    return _holding_signals(prices, features, params["holding_days"])


def deals_signals(prices, features, params):
    return _holding_signals(prices, features, 1)


def post_results_signals(prices, features, params):
    _check_features(prices, features)
    traded, signals = set(), []
    for row in features.itertuples():
        key = row.symbol, row.Index.normalize()
        if key not in traded and row.eligible and row.close > row.range_high:
            if row.Index.hour * 60 + row.Index.minute < 15 * 60 + 15:
                signals.append(Signal(row.Index, row.symbol, 1))
                traded.add(key)
    return signals


def results_day_filter(strategy):
    """Wrap an intraday rule; built-in variants are registered at import time."""
    from autopsy.strategies import Strategy
    if strategy.mode != "intraday" or strategy.name.endswith("+results_filter"):
        raise ValueError("results filter requires an unfiltered intraday strategy")

    def features(prices, params):
        return strategy.features(prices, params)

    def signals(prices, features, params):
        opens = _opens(prices)
        blocked = set()
        for event in events_from_prices(prices):
            if event.kind not in {"results", "board_meeting"} or event.disseminated_at is None:
                continue
            day = pd.Timestamp(event.scheduled_for or event.disseminated_at.date(), tz="Asia/Kolkata")
            if day in opens and event.disseminated_at < opens[day]:
                blocked.add((event.symbol, day))
        return [signal for signal in strategy.signals(prices, features, params)
                if signal.target == 0 or (signal.symbol, signal.time.normalize()) not in blocked]

    def data_check(prices):
        check = _check(prices, {"results", "board_meeting"}, intraday=False)
        if check.verdict != "PASS" or strategy.data_check is None:
            return check
        return strategy.data_check(prices)

    return Strategy(strategy.name + "+results_filter", strategy.mode, strategy.params_grid,
                    features, signals, data_check)
