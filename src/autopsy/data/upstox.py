"""Read-only Upstox V3 historical candles; verified official docs 2026-11-02.

https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/
https://upstox.com/developer/api-documentation/analytics-token/

GET https://api.upstox.com/v3/historical-candle/{instrument_key}/{unit}/
{interval}/{to_date}/{from_date}, inclusive dates. Response: status='success',
data.candles = [[timestamp, open, high, low, close, volume, open_interest], ...].
Minutes 1..300 and hours 1..5 start January 2022; days/weeks/months accept 1
and start January 2000. The documented request caps are one month for minutes
1..15, one quarter for longer minutes and hours, a decade for days, unlimited
for weeks/months. We conservatively chunk ALL minutes at calendar-month
boundaries, hours into <=3 months, days into <=10 years. 429 retries wait
1, 2, 4 seconds (three retries); other failures are sanitized, not retried.

Analytics tokens are free, read-only, valid one year; historical data needs
no static IP. Generate at Upstox → Developer Apps → Analytics → generate token.
Default credential file: ~/.config/oracle-autopsy/upstox_analytics_token,
mode 600. Never log tokens, response bodies, headers or transport exceptions.
No order API exists here. Request-result caches are verified Parquet snapshots
under AUTOPSY_DATA_DIR/upstox; cache=False bypasses them. Every result has the
observed-session expected_bars JSON grid documented in data.schedule.
"""

from datetime import date, datetime
import hashlib
import json
from numbers import Integral
from pathlib import Path
import re
import stat
import time
from urllib.parse import quote

import httpx
import pandas as pd

from autopsy.data.schedule import combine_prices, with_schedule
from autopsy.data.store import _write_snapshot, data_dir, load_snapshot


DEFAULT_TOKEN_PATH = Path("~/.config/oracle-autopsy/upstox_analytics_token")
_BASE = "https://api.upstox.com/v3/historical-candle"


class TokenMissing(RuntimeError):
    """Absent, insecure, unreadable, rejected or expired Analytics credential."""

    def __init__(self, path):
        super().__init__(f"Upstox Analytics token unavailable or expired: {path}. "
                         "Upstox → Developer Apps → Analytics → generate token; "
                         "save it to this file with mode 600.")


class UpstoxError(RuntimeError):
    """Sanitized historical-data failure (contains no response or headers)."""


def _day(value):
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return pd.Timestamp(date.fromisoformat(value), tz="Asia/Kolkata")
    if isinstance(value, date) and not isinstance(value, datetime):
        return pd.Timestamp(value, tz="Asia/Kolkata")
    value = pd.Timestamp(value)
    if pd.isna(value) or value.tz is None:
        raise ValueError("request timestamps must be tz-aware; date-only YYYY-MM-DD strings are allowed")
    return value.tz_convert("Asia/Kolkata").normalize()


def _chunks(start, end, unit):
    cursor = start
    while cursor <= end:
        if unit == "minutes":
            following = cursor + pd.offsets.MonthBegin(1)
        elif unit == "hours":
            following = cursor + pd.DateOffset(months=3)
        elif unit == "days":
            following = cursor + pd.DateOffset(years=10)
        else:
            following = end + pd.Timedelta(days=1)
        last = min(end, following - pd.Timedelta(days=1))
        yield cursor, last
        cursor = last + pd.Timedelta(days=1)


class UpstoxClient:
    def __init__(self, token_path=DEFAULT_TOKEN_PATH, *, transport=None, sleep=time.sleep,
                 cache=True, cache_dir=None):
        self.token_path = Path(token_path).expanduser()
        self._transport = transport
        self._sleep = sleep
        self._cache = cache
        self._cache_dir = Path(cache_dir).expanduser() if cache_dir is not None else data_dir() / "upstox"
        try:
            mode = stat.S_IMODE(self.token_path.stat().st_mode)
            token = self.token_path.read_text(encoding="utf-8").strip() if mode == 0o600 else ""
        except (OSError, UnicodeError):
            token = ""
        if not token or not token.isascii() or any(ch.isspace() for ch in token):
            raise TokenMissing(self.token_path) from None
        self._token = token

    def _request(self, url):
        try:
            with httpx.Client(transport=self._transport, timeout=30., follow_redirects=False,
                              trust_env=False) as client:
                for attempt in range(4):
                    response = client.get(url, headers={"Authorization": f"Bearer {self._token}",
                                                        "Accept": "application/json"})
                    if response.status_code in (401, 403):
                        raise TokenMissing(self.token_path)
                    if response.status_code == 429 and attempt < 3:
                        response.close()
                        self._sleep(float(2 ** attempt))
                        continue
                    if response.status_code != 200:
                        raise UpstoxError(f"Upstox historical candles failed (HTTP {response.status_code})")
                    return response.json()
        except (httpx.HTTPError, ValueError):
            raise UpstoxError("Upstox historical candles transport or JSON failure") from None

    def candles(self, instrument_key, unit, interval, start, end):
        """Fetch/cached-load a cash instrument's OHLCV, sorted and aware in IST."""
        limits = {"minutes": 300, "hours": 5, "days": 1, "weeks": 1, "months": 1}
        if (unit not in limits or isinstance(interval, bool) or not isinstance(interval, Integral)
                or not 1 <= interval <= limits[unit]):
            raise ValueError("unsupported candle unit/interval")
        if not isinstance(instrument_key, str) or not re.fullmatch(r"(?:NSE_EQ|BSE_EQ|NSE_INDEX|BSE_INDEX)\|[^\s/]+(?: [^\s/]+)*", instrument_key):
            raise ValueError("instrument_key must identify a cash equity/ETF or index")
        first, last = _day(start), _day(end)
        earliest = pd.Timestamp("2022-01-01" if unit in ("minutes", "hours") else "2000-01-01", tz="Asia/Kolkata")
        if first < earliest or last < first:
            raise ValueError("request dates outside historical availability or reversed")
        freq = {"minutes": f"{interval}min", "hours": f"{interval}h", "days": "1D",
                "weeks": "1W", "months": "1MS"}[unit]
        frames = []
        for lower, upper in _chunks(first, last, unit):
            url = f"{_BASE}/{quote(instrument_key, safe='')}/{unit}/{interval}/{upper.date()}/{lower.date()}"
            key = hashlib.sha256(url.encode()).hexdigest()
            path = self._cache_dir / f"{key}.parquet"
            if self._cache and path.exists() and path.with_suffix(".json").exists():
                frame, _ = load_snapshot(path)
            else:
                payload = self._request(url)
                try:
                    frame = _frame(payload, instrument_key)
                    if ((frame.index.normalize() < lower) | (frame.index.normalize() > upper)).any():
                        raise ValueError()
                    frame = with_schedule(frame, freq)
                except (KeyError, TypeError, ValueError, OverflowError):
                    raise UpstoxError("Invalid Upstox V3 candle response; expected aware OHLCV arrays") from None
                if self._cache:
                    _write_snapshot(frame, path, "raw", url)
            frames.append(frame)
        return combine_prices(frames)

    def intraday(self, instrument_key, unit, interval):
        """Today's candles so far, ascending, never cached; the newest may still be forming.

        GET .../v3/historical-candle/intraday/{instrument_key}/{unit}/{interval}
        (https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/).
        The docs show newest-first rows and do not say whether Analytics
        Tokens are accepted here; untested against the live API.
        """
        limits = {"minutes": 300, "hours": 5, "days": 1}
        if (unit not in limits or isinstance(interval, bool) or not isinstance(interval, Integral)
                or not 1 <= interval <= limits[unit]):
            raise ValueError("unsupported candle unit/interval")
        url = f"{_BASE}/intraday/{quote(instrument_key, safe='')}/{unit}/{interval}"
        try:
            return _frame(self._request(url), instrument_key)
        except (KeyError, TypeError, ValueError, OverflowError):
            raise UpstoxError("Invalid Upstox V3 intraday response; expected aware OHLCV arrays") from None


def _frame(payload, instrument_key):
    """Upstox candle payload → ascending IST OHLCV frame; raises ValueError on any malformed row."""
    if payload["status"] != "success":
        raise ValueError()
    rows = payload["data"]["candles"]
    if not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != 7 for row in rows):
        raise ValueError()
    times = [pd.Timestamp(row[0]) for row in rows]
    if any(pd.isna(t) or t.tz is None for t in times):
        raise ValueError()
    index = pd.DatetimeIndex([t.tz_convert("Asia/Kolkata") for t in times], tz="Asia/Kolkata", name="time")
    frame = pd.DataFrame([row[1:6] for row in rows], columns=["open", "high", "low", "close", "volume"],
                         index=index).astype(float)
    frame.insert(0, "symbol", instrument_key)
    return frame.sort_index()
