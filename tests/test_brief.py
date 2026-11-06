from urllib.parse import parse_qs, urlsplit

import httpx
import pandas as pd
import pytest

from autopsy.alerts.brief import LOGIN_NEEDED, format_brief
from autopsy.cli import main
from autopsy.data.kite import KiteError
from tests.test_kite import client_for, files  # noqa: F401  (fixture)

IST = "Asia/Kolkata"
NOW = pd.Timestamp("2026-11-06 18:30", tz=IST)
TODAY = pd.Timestamp("2026-11-06 15:29:59", tz=IST)


def q(last, prev, at=TODAY):
    return {"last_price": last, "prev_close": prev, "last_trade_time": at}


def closes(n, value=100.0):
    days = pd.bdate_range(end="2026-11-05", periods=n)
    return pd.Series([value] * n, index=days)


def test_brief_shows_regime_moves_and_status():
    quotes = {"NSE:NIFTY 50": q(110.0, 100.0, None), "NSE:INDIA VIX": q(12.0, 15.0, None),
              "NSE:AAA": q(105, 100), "NSE:BBB": q(98, 100), "NSE:CCC": q(100, 100),
              "NSE:DDD": q(103, 100)}
    text = format_brief(quotes, closes(250), now=NOW, status="none cleared")
    assert "Fri 06 Nov 2026, 18:30 IST" in text
    assert "Nifty 50 110.00 (+10.00%), above its 200-day average 100 (regime ON)" in text
    assert "India VIX 12.00 (-20.00%)" in text
    assert "Tracked stocks: 2 up, 1 down of 4" in text
    assert "Top: AAA +5.0%, DDD +3.0%, CCC +0.0%" in text
    assert "Bottom: BBB -2.0%" in text
    assert "Strategy: none cleared" in text and "Not investment advice" in text
    assert "Market closed" not in text


def test_brief_flags_holiday_and_short_history():
    friday = pd.Timestamp("2026-11-05 15:29:00", tz=IST)
    quotes = {"NSE:NIFTY 50": q(90.0, 100.0), "NSE:AAA": q(101, 100, friday)}
    text = format_brief(quotes, closes(50), now=NOW)
    assert "Market closed today. Figures are from Thu 05 Nov." in text
    assert "200-day regime unknown" in text


def test_regime_uses_only_closes_before_the_session():
    history = closes(199, 100.0)
    history[pd.Timestamp("2026-11-06")] = 1_000_000.0  # today's bar must not be double counted
    text = format_brief({"NSE:NIFTY 50": q(80.0, 100.0), "NSE:AAA": q(1, 1)}, history, now=NOW)
    assert "below its 200-day average 100 (regime OFF)" in text


def test_quotes_parse_and_request_all_symbols(files):  # noqa: F811
    seen = []

    def handle(request):
        seen.append(parse_qs(urlsplit(str(request.url)).query)["i"])
        return httpx.Response(200, json={"status": "success", "data": {
            "NSE:AAA": {"last_price": 101.5, "ohlc": {"close": 100.0}, "last_trade_time": "2026-11-05 15:29:59"},
            "NSE:NIFTY 50": {"last_price": 24000, "ohlc": {"close": 23900}, "timestamp": "2026-11-05 15:30:00"}}})

    result = client_for(files, handle).quotes(["NSE:AAA", "NSE:NIFTY 50", "NSE:MISSING"])
    assert seen == [["NSE:AAA", "NSE:NIFTY 50", "NSE:MISSING"]]
    assert result["NSE:AAA"] == {"last_price": 101.5, "prev_close": 100.0,
                                 "last_trade_time": pd.Timestamp("2026-11-05 15:29:59", tz=IST)}
    assert "NSE:MISSING" not in result


def test_quotes_reject_bad_input_and_bad_response(files):  # noqa: F811
    client = client_for(files, lambda request: httpx.Response(200, json={"status": "success", "data": {
        "NSE:AAA": {"last_price": "x", "ohlc": {}}}}))
    with pytest.raises(ValueError):
        client.quotes([])
    with pytest.raises(KiteError, match="Invalid Kite quote"):
        client.quotes(["NSE:AAA"])


def test_cli_sends_login_reminder_when_session_missing(tmp_path, capsys):
    symbols = tmp_path / "s.txt"
    symbols.write_text("NSE:AAA\n")
    code = main(["brief", "--symbols", str(symbols), "--credentials", str(tmp_path / "none.json"),
                 "--session", str(tmp_path / "none2.json")])
    assert code == 2
    assert LOGIN_NEEDED in capsys.readouterr().out
