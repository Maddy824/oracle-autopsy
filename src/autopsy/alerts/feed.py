"""Bar sources for paper alerts and the market-hours loop that watches them."""

import csv
import time as _time

import pandas as pd

from autopsy.alerts.notify import format_alert
from autopsy.alerts.orb import BAR, Alert, orb_alerts
from autopsy.data.store import data_dir


IST = "Asia/Kolkata"
FIELDS = ["symbol", "time", "side", "price", "reason", "range_high", "range_low", "stop", "target"]


def alerts_dir():
    return data_dir() / "alerts"


def completed(bars, now):
    """Drop bars still forming at `now`; a bar is complete once its five minutes end."""
    return bars[bars.index + BAR <= now]


def replay(prices):
    """Every alert for every session and symbol in a multi-symbol bar frame."""
    alerts = []
    for (_, symbol), bars in prices.groupby([prices.index.normalize(), "symbol"]):
        alerts += orb_alerts(symbol, bars, final=True)
    return sorted(alerts, key=lambda a: (a.time, a.symbol))


class UpstoxIntradayFeed:
    """Today's five-minute bars from Upstox, keyed by display symbol."""

    def __init__(self, client, instruments):
        self.client, self.instruments = client, instruments

    def bars(self, symbol, now):
        return completed(self.client.intraday(self.instruments[symbol], "minutes", 5), now)


def append_log(alerts, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, FIELDS)
        if new:
            writer.writeheader()
        writer.writerows(alert.row() for alert in alerts)


def run_live(feed, symbols, notifier, *, now=lambda: pd.Timestamp.now(tz=IST), sleep=_time.sleep,
             directory=None):
    """Check every symbol 10 s after each five-minute boundary until 15:16 IST.

    Alerts go to the notifier and the CSV log once each. An alert older than
    ten minutes (a late start or a feed gap) is marked LATE. The session's
    bars are saved for the evening scorecard.
    """
    directory = directory or alerts_dir()
    day = now().normalize()
    stop = day + pd.Timedelta(hours=15, minutes=16)
    sent, latest = set(), {}
    while (current := now()) < stop:
        for symbol in symbols:
            try:
                bars = feed.bars(symbol, current)
            except Exception as exc:  # keep watching the other symbols; never echo payloads
                notifier.send(f"Data problem for {symbol} ({type(exc).__name__}). Skipping this check.")
                continue
            latest[symbol] = bars
            for alert in orb_alerts(symbol, bars):
                if (alert.symbol, alert.side) in sent:
                    continue
                sent.add((alert.symbol, alert.side))
                late = "LATE " if current - alert.time > pd.Timedelta(minutes=10) else ""
                notifier.send(late + format_alert(alert))
                append_log([alert], directory / "alerts.csv")
        wake = current.floor("5min") + BAR + pd.Timedelta(seconds=10)
        sleep(max(1., (wake - now()).total_seconds()))
    frames = [bars.assign(symbol=symbol) for symbol, bars in latest.items() if len(bars)]
    if frames:
        (directory / "bars").mkdir(parents=True, exist_ok=True)
        pd.concat(frames).to_parquet(directory / "bars" / f"{day.date()}.parquet")
    return sent


def load_history(directory=None):
    """Logged alerts and saved session bars from earlier live days, or (None, None)."""
    directory = directory or alerts_dir()
    log = directory / "alerts.csv"
    files = sorted((directory / "bars").glob("*.parquet"))
    if not log.exists() or not files:
        return None, None
    alerts = [Alert(**{**row, "time": pd.Timestamp(row["time"]).tz_convert(IST)})
              for row in pd.read_csv(log).to_dict("records")]
    return alerts, pd.concat(pd.read_parquet(path) for path in files).sort_index()
