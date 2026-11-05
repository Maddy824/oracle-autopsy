"""Session dates and intraday exits inferred from the supplied bars.

This describes observed sessions; it cannot distinguish a short session from
missing data. Missing-bar quality checks need an independent expected schedule.

Intraday CLI research first restricts every symbol and date to bar starts before
15:15 IST, with matching expected slots. Thus its five-minute sessions exit at
the 15:10 bar (at its open in the engine). This common window avoids the closing
auction introduced for F&O stocks on 3 August 2026. The announced 7 December
2026 move to 15:30–15:40 does not change this fixed research convention. Swing,
daily data and saved raw inputs retain their original sessions.
"""

import pandas as pd

from autopsy.types import _ist_index


def trading_days(prices: pd.DataFrame) -> pd.DatetimeIndex:
    """Return sorted, distinct observed trading dates at midnight in IST."""
    return _ist_index(prices.index, "prices").normalize().unique().sort_values()


def _intraday_closes(prices: pd.DataFrame) -> dict[tuple[str, pd.Timestamp], pd.Timestamp]:
    """Choose each symbol's exit bar without inventing a tradable bar.

    Regular sessions exit at the first observed bar at/after 15:15, or the
    last bar when shorter. Sessions starting after 15:15 exit at their last
    bar, allowing evening special sessions. Availability is session metadata,
    not a guarantee that the source data is complete.
    """
    closes = {}
    for (symbol, day), bars in prices.groupby(["symbol", prices.index.normalize()]):
        times = bars.index.sort_values()
        deadline = day + pd.Timedelta(hours=15, minutes=15)
        later = times[times >= deadline]
        closes[symbol, day] = (
            later[0] if times[0] <= deadline and len(later) else times[-1]
        )
    return closes
