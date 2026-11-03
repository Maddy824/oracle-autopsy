"""Paper alerts for the 15-minute opening-range breakout, long only.

Input is one symbol's completed five-minute bars for one session, indexed by
bar start in IST. The range is the 09:15-09:30 high and low. BUY fires on the
first bar closing above the range high, if that bar closes by 11:00. SELL
fires on the first later bar that closes below the range low (stop), closes
at or above entry + 2R (target, R = entry - range low), or closes at 15:15
(time). Fills are the alert bar's close moved 5 bps against the trade.

The function only reads the bars it is given, so calling it on a growing
prefix of the session never sees the future: earlier alerts never change.
"""

from dataclasses import asdict, dataclass

import pandas as pd


SLIPPAGE = 0.0005
BAR = pd.Timedelta(minutes=5)
OPEN, RANGE_END, LAST_ENTRY, FLAT = "09:15", "09:30", "11:00", "15:15"


@dataclass(frozen=True)
class Alert:
    symbol: str
    time: pd.Timestamp  # close time of the bar that fired the alert
    side: str  # BUY or SELL
    price: float  # paper fill, slippage included
    reason: str  # breakout, stop, target, time or data_end
    range_high: float
    range_low: float
    stop: float
    target: float

    def row(self):
        return {**asdict(self), "time": self.time.isoformat()}


def _at(day, hhmm):
    return day + pd.Timedelta(hours=int(hhmm[:2]), minutes=int(hhmm[3:]))


def orb_alerts(symbol, bars, *, final=False):
    """Return the session's alerts so far; final closes an open trade at the last bar."""
    if bars.empty:
        return []
    bars = bars.sort_index()
    day = bars.index[0].normalize()
    if (bars.index.normalize() != day).any():
        raise ValueError("orb_alerts takes one session at a time")
    opening = bars[(bars.index >= _at(day, OPEN)) & (bars.index < _at(day, RANGE_END))]
    if len(opening) < 3:
        return []
    high, low = float(opening["high"].max()), float(opening["low"].min())
    alerts, entry = [], None
    rest = bars[bars.index >= _at(day, RANGE_END)]
    for start, row in rest.iterrows():
        closed = start + BAR
        if entry is None:
            if closed > _at(day, LAST_ENTRY):
                break
            if row["close"] > high:
                price = float(row["close"]) * (1 + SLIPPAGE)
                entry = Alert(symbol, closed, "BUY", price, "breakout", high, low,
                              low, price + 2 * (price - low))
                alerts.append(entry)
            continue
        reason = ("stop" if row["close"] < low else "target" if row["close"] >= entry.target
                  else "time" if closed >= _at(day, FLAT) else None)
        if reason:
            alerts.append(_exit(entry, closed, float(row["close"]), reason))
            return alerts
    if final and entry is not None and len(alerts) == 1 and len(rest):
        alerts.append(_exit(entry, rest.index[-1] + BAR, float(rest["close"].iloc[-1]), "data_end"))
    return alerts


def _exit(entry, time, close, reason):
    return Alert(entry.symbol, time, "SELL", close * (1 - SLIPPAGE), reason,
                 entry.range_high, entry.range_low, entry.stop, entry.target)
