"""Read-only Kite Connect v3 history; contract verified 2026-11-05.

https://kite.trade/docs/connect/v3/user/
https://kite.trade/docs/connect/v3/historical/
https://kite.trade/docs/connect/v3/market-quotes/#instruments
https://kite.trade/docs/connect/v3/exceptions/
https://kite.trade/forum/discussion/14381/in-historical-data-are-prices-adjusted-for-splits-and-bonus
https://kite.trade/forum/discussion/4014/is-historical-data-dividend-adjusted

Base https://api.kite.trade; every request sends X-Kite-Version: 3, and
authenticated data requests send Authorization: token api_key:access_token.
Login URL: https://kite.zerodha.com/connect/login?v=3&api_key={api_key}.
The registered redirect http://127.0.0.1 need not have a listener: paste the
error page's address-bar URL with request_token, action=login, status=success.
POST /session/token exchanges api_key, request_token and SHA256(api_key +
request_token + api_secret), form-encoded. Request tokens are single-use,
valid a few minutes. Sessions expire at the next 06:00 IST after login.

GET /instruments/historical/{instrument_token}/{interval}, with from/to IST
wall times (yyyy-mm-dd hh:mm:ss), continuous=0, oi=0. Success data.candles
contains [aware timestamp (e.g. +0530), O,H,L,C,V] (optionally OI seventh).
Forum/staff span caps: minute 60 days; 3/5/10minute 100; 15/30minute 200;
60minute 400; day 2000. Use one day LESS per chunk. Space requests >=0.35s
(3/s limit); 429 retries wait 1,2,4s. HTTP 403 or TokenException means login
again; all failures are sanitized without response bodies or headers.
GET /instruments/{exchange} is daily CSV, sometimes gzip. Resolve by exchange
and tradingsymbol, never retain a token mapping across IST dates: tokens can
be reused. NIFTY 50 is tradingsymbol 'NIFTY 50', segment 'INDICES'. Verified
Parquet chunk caches use token, interval and bounds, never authentication.
CSV columns: instrument_token, exchange_token, tradingsymbol, name,
last_price, expiry, strike, tick_size, lot_size, instrument_type, segment,
exchange. Cache entries retain the resolved symbol to detect token reuse.

Historical candles are split/bonus-adjusted, not dividend-adjusted: label
price_basis='adjusted' and never apply split/bonus actions again. Static IP
whitelisting applies to order placement only; data needs no static IP.
This module has no order endpoints. Credentials and session files must be
mode 600. Session writes are atomic and private from the moment of creation.
"""

from datetime import date, datetime
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import httpx
import pandas as pd

from autopsy.data.schedule import combine_prices, with_schedule
from autopsy.data.store import _write_snapshot, data_dir, load_snapshot


DEFAULT_CREDENTIALS_PATH = Path("~/.config/oracle-autopsy/kite.json")
DEFAULT_SESSION_PATH = Path("~/.config/oracle-autopsy/kite_session.json")
_BASE = "https://api.kite.trade"
_IST = "Asia/Kolkata"
_CAPS = {"minute": 60, "3minute": 100, "5minute": 100, "10minute": 100,
         "15minute": 200, "30minute": 200, "60minute": 400, "day": 2000}


class KiteError(RuntimeError):
    """Sanitized failure; never contains a response, header or credential."""


class KiteCredentialsMissing(KiteError):
    def __init__(self):
        super().__init__("Kite credentials unavailable: save api_key and api_secret in the "
                         "credentials JSON file with mode 600, then run autopsy kite login.")


class KiteSessionMissing(KiteError):
    def __init__(self):
        super().__init__("Kite session unavailable or expired; run autopsy kite login.")


def _now(now=None):
    value = now() if callable(now) else now
    return pd.Timestamp.now(tz=_IST) if value is None else _ist(value)


def _ist(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError()
    return stamp.tz_localize(_IST) if stamp.tz is None else stamp.tz_convert(_IST)


def _expires(login):
    boundary = login.normalize() + pd.Timedelta(hours=6)
    return boundary if login < boundary else boundary + pd.Timedelta(days=1)


def _private_json(path, error):
    try:
        path = Path(path).expanduser()
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise ValueError()
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError, UnicodeError):
        raise error() from None


def _credential(value):
    return (isinstance(value, str) and bool(value) and value.isascii()
            and all(33 <= ord(ch) <= 126 for ch in value))


def read_credentials(path=DEFAULT_CREDENTIALS_PATH):
    credentials = _private_json(path, KiteCredentialsMissing)
    if not all(_credential(credentials.get(key)) for key in ("api_key", "api_secret")):
        raise KiteCredentialsMissing()
    return credentials


def login_url(api_key):
    if not _credential(api_key):
        raise KiteCredentialsMissing()
    return "https://kite.zerodha.com/connect/login?" + urlencode({"v": "3", "api_key": api_key})


def parse_request_token(text):
    """Accept a redirect URL or alphanumeric token, without echoing either."""
    try:
        token = text.strip()
        if not re.fullmatch(r"[A-Za-z0-9]+", token):
            url = urlsplit(token)
            if url.scheme not in ("http", "https") or not url.netloc or url.fragment:
                raise ValueError()
            query = parse_qs(url.query, keep_blank_values=True)
            if "status" in query and query["status"] != ["success"]:
                raise ValueError()
            tokens = query.get("request_token", [])
            if len(tokens) != 1:
                raise ValueError()
            token = tokens[0]
        if not re.fullmatch(r"[A-Za-z0-9]+", token):
            raise ValueError()
        return token
    except (AttributeError, TypeError, ValueError):
        raise ValueError("Invalid Kite login response; paste the successful redirect URL or request token.") from None


def _payload(response):
    if response.status_code in (401, 403):
        raise KiteSessionMissing()
    try:
        payload = response.json()
    except ValueError:
        raise KiteError("Kite response JSON failure") from None
    if isinstance(payload, dict) and payload.get("error_type") == "TokenException":
        raise KiteSessionMissing()
    if response.status_code != 200:
        raise KiteError(f"Kite request failed (HTTP {response.status_code})")
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise KiteError("Kite request failed")
    return payload


def create_session(credentials_path, session_path, request_token, *, transport=None, now=None):
    credentials = read_credentials(credentials_path)
    token = parse_request_token(request_token)
    checksum = hashlib.sha256((credentials["api_key"] + token + credentials["api_secret"]).encode()).hexdigest()
    try:
        with httpx.Client(transport=transport, timeout=30., follow_redirects=False, trust_env=False) as client:
            response = client.post(_BASE + "/session/token", headers={"X-Kite-Version": "3"},
                                   data={"api_key": credentials["api_key"], "request_token": token,
                                         "checksum": checksum})
            data = _payload(response)["data"]
        access = data["access_token"]
        login = _ist(data["login_time"])
        expires = _expires(login)
        if not _credential(access):
            raise ValueError()
        if expires <= _now(now):
            raise KiteSessionMissing()
    except (httpx.HTTPError, KeyError, TypeError, ValueError, OverflowError):
        raise KiteError("Kite session exchange failed; run autopsy kite login again.") from None
    session = {"access_token": access, "login_time": login.isoformat(), "expires_at": expires.isoformat()}
    path = Path(session_path).expanduser()
    temp = path.with_name("." + uuid4().hex + ".tmp")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(session, stream)
            stream.write("\n")
        temp.replace(path)
    except OSError:
        raise KiteError("Cannot save Kite session; check the private session directory.") from None
    finally:
        temp.unlink(missing_ok=True)
    return session


def _bound(value, *, end=False):
    is_date = ((isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))
               or (isinstance(value, date) and not isinstance(value, datetime)))
    stamp = pd.Timestamp(value)
    if is_date:
        stamp = stamp.tz_localize(_IST)
        return stamp + pd.Timedelta(days=1) - pd.Timedelta(seconds=1) if end else stamp
    if pd.isna(stamp) or stamp.tz is None:
        raise ValueError("request timestamps must be tz-aware; date-only YYYY-MM-DD strings are allowed")
    if stamp != stamp.floor("s"):
        raise ValueError("request timestamps must have whole-second precision")
    return stamp.tz_convert(_IST)


def _chunks(first, last, interval):
    cursor = first
    while cursor <= last:
        upper = min(last, cursor + pd.Timedelta(days=_CAPS[interval] - 1) - pd.Timedelta(seconds=1))
        yield cursor, upper
        cursor = upper + pd.Timedelta(seconds=1)


class KiteClient:
    def __init__(self, credentials_path=DEFAULT_CREDENTIALS_PATH, session_path=DEFAULT_SESSION_PATH,
                 *, transport=None, sleep=time.sleep, clock=time.monotonic, now=None,
                 cache=True, cache_dir=None):
        credentials = read_credentials(credentials_path)
        session = _private_json(session_path, KiteSessionMissing)
        try:
            login, expires = _ist(session["login_time"]), pd.Timestamp(session["expires_at"])
            if (pd.isna(expires) or expires.tz is None or expires != _expires(login)
                    or expires <= _now(now) or not _credential(session["access_token"])):
                raise ValueError()
        except (KeyError, TypeError, ValueError, OverflowError):
            raise KiteSessionMissing() from None
        self._api_key, self._access_token = credentials["api_key"], session["access_token"]
        self._expires_at = expires
        self._transport, self._sleep, self._clock, self._now = transport, sleep, clock, now
        self._last_request = None
        self._cache = cache
        self._cache_dir = Path(cache_dir).expanduser() if cache_dir is not None else data_dir() / "kite"

    def _request(self, path, *, params=None, csv=False):
        if _now(self._now) >= self._expires_at:
            raise KiteSessionMissing()
        try:
            with httpx.Client(transport=self._transport, timeout=30., follow_redirects=False,
                              trust_env=False) as client:
                for attempt in range(4):
                    if self._last_request is not None:
                        delay = .35 - (self._clock() - self._last_request)
                        if delay > 0:
                            self._sleep(delay)
                    self._last_request = self._clock()
                    response = client.get(_BASE + path, params=params,
                                          headers={"X-Kite-Version": "3",
                                                   "Authorization": f"token {self._api_key}:{self._access_token}"})
                    if response.status_code in (401, 403):
                        raise KiteSessionMissing()
                    if response.status_code == 429 and attempt < 3:
                        response.close()
                        self._sleep(float(2 ** attempt))
                        continue
                    if csv and response.status_code == 200 and not response.content.lstrip().startswith(b"{"):
                        return response.content
                    return _payload(response)
        except (httpx.HTTPError, ValueError):
            raise KiteError("Kite transport or response failure") from None

    def instruments(self, exchange="NSE"):
        if not isinstance(exchange, str) or not re.fullmatch(r"[A-Z]+", exchange):
            raise ValueError("exchange must be an uppercase exchange code")
        path = self._cache_dir / f"instruments-{exchange}-{_now(self._now).date()}.csv"
        cached = self._cache and path.exists()
        content = path.read_bytes() if cached else self._request(f"/instruments/{exchange}", csv=True)
        try:
            if content.startswith(b"\x1f\x8b"):
                content = gzip.decompress(content)
            frame = pd.read_csv(io.BytesIO(content), dtype={"instrument_token": str}, keep_default_na=False)
            if not {"instrument_token", "exchange", "tradingsymbol", "segment"} <= set(frame):
                raise ValueError()
            if (not frame.instrument_token.str.fullmatch(r"[0-9]+").all()
                    or (frame.instrument_token.astype("int64") <= 0).any()
                    or (frame.exchange != exchange).any() or (frame.tradingsymbol == "").any()):
                raise ValueError()
        except (AttributeError, OSError, EOFError, TypeError, ValueError, OverflowError):
            raise KiteError("Invalid Kite instruments CSV") from None
        if self._cache and not cached:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name("." + uuid4().hex + ".tmp")
            try:
                temp.write_bytes(content)
                temp.replace(path)
            finally:
                temp.unlink(missing_ok=True)
        return frame

    def resolve(self, symbol):
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z]+:[^:\r\n]+", symbol):
            raise ValueError("symbol must be EXCHANGE:TRADINGSYMBOL")
        exchange, name = symbol.split(":", 1)
        frame = self.instruments(exchange)
        matches = frame[(frame.exchange == exchange) & (frame.tradingsymbol == name)]
        if len(matches) != 1:
            raise ValueError("Unknown Kite symbol" if matches.empty else "Ambiguous Kite symbol")
        return int(matches.instrument_token.iloc[0])

    def candles(self, symbol, interval, start, end):
        """Inclusive dates or precise aware bounds; sorted, scheduled, adjusted IST OHLCV."""
        if interval not in _CAPS:
            raise ValueError("unsupported Kite candle interval")
        first, last = _bound(start), _bound(end, end=True)
        if last < first:
            raise ValueError("request dates are reversed")
        token = self.resolve(symbol)
        freq = "1D" if interval == "day" else ("1min" if interval == "minute" else interval.replace("minute", "min"))
        frames = []
        for lower, upper in _chunks(first, last, interval):
            params = {"from": lower.strftime("%Y-%m-%d %H:%M:%S"), "to": upper.strftime("%Y-%m-%d %H:%M:%S"),
                      "continuous": "0", "oi": "0"}
            endpoint = f"/instruments/historical/{token}/{interval}"
            source = _BASE + endpoint + "?" + urlencode(params)
            key = hashlib.sha256(source.encode()).hexdigest()
            path = self._cache_dir / f"{key}.parquet"
            cached = self._cache and path.exists() and path.with_suffix(".json").exists()
            if cached:
                frame, _ = load_snapshot(path)
                # Reused tokens must not return another instrument's cached history.
                cached = frame.attrs.get("kite_symbol") == symbol and (frame.symbol == symbol).all()
            if not cached:
                frame = _frame(self._request(endpoint, params=params), symbol)
            try:
                if ((frame.index < lower) | (frame.index > upper)).any():
                    raise ValueError()
                frame = with_schedule(frame, freq)
            except (KeyError, TypeError, ValueError, OverflowError):
                raise KiteError("Invalid Kite candles; expected aware OHLCV within request bounds") from None
            frame.attrs["price_basis"] = "adjusted"
            frame.attrs["kite_symbol"] = symbol
            if self._cache and not cached:
                _write_snapshot(frame, path, "adjusted", source)
            frames.append(frame)
        return combine_prices(frames)


def _frame(payload, symbol):
    try:
        rows = payload["data"]["candles"]
        if not isinstance(rows, list) or any(not isinstance(row, list) or len(row) not in (6, 7) for row in rows):
            raise ValueError()
        times = [pd.Timestamp(row[0]) for row in rows]
        if any(pd.isna(t) or t.tz is None for t in times):
            raise ValueError()
        index = pd.DatetimeIndex([t.tz_convert(_IST) for t in times], tz=_IST, name="time")
        frame = pd.DataFrame([row[1:6] for row in rows], columns=["open", "high", "low", "close", "volume"],
                             index=index).astype(float)
        frame.insert(0, "symbol", symbol)
        return frame.sort_index()
    except (KeyError, TypeError, ValueError, OverflowError):
        raise KiteError("Invalid Kite candle response; expected aware OHLCV arrays") from None
