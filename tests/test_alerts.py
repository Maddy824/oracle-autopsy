import json

import httpx
import numpy as np
import pandas as pd
import pytest

from autopsy.alerts.feed import completed, load_history, replay, run_live
from autopsy.alerts.notify import TelegramError, TelegramNotifier, format_alert
from autopsy.alerts.orb import SLIPPAGE, orb_alerts
from autopsy.alerts.scorecard import random_entries, summarise, trades
from autopsy.cli import main
from autopsy.costs import load_rates
from autopsy.data.upstox import UpstoxClient


DAY = pd.Timestamp("2025-03-03", tz="Asia/Kolkata")


def session(closes, symbol="ABC", day=DAY):
    index = pd.DatetimeIndex([day + pd.Timedelta(minutes=555 + 5 * i) for i in range(len(closes))], name="time")
    closes = np.asarray(closes, float)
    return pd.DataFrame({"symbol": symbol, "open": closes, "high": closes, "low": closes,
                         "close": closes, "volume": 1000.}, index=index)


def full_day(after_range):
    # 3 range bars (high 101, low 99), then the given closes, padded flat to 75 bars.
    closes = [100, 101, 99] + list(after_range)
    return session(closes + [closes[-1]] * (75 - len(closes)))


def test_breakout_then_target():
    alerts = orb_alerts("ABC", full_day([100, 102, 104, 110]))
    buy, sell = alerts
    assert (buy.side, buy.reason, str(buy.time.time())) == ("BUY", "breakout", "09:40:00")
    assert buy.price == pytest.approx(102 * (1 + SLIPPAGE))
    assert buy.target == pytest.approx(buy.price + 2 * (buy.price - 99))
    assert (sell.side, sell.reason) == ("SELL", "target")
    assert sell.price == pytest.approx(110 * (1 - SLIPPAGE))


def test_stop_and_time_exits():
    assert orb_alerts("ABC", full_day([102, 98.5]))[1].reason == "stop"
    exit_ = orb_alerts("ABC", full_day([102]))[1]
    assert (exit_.reason, str(exit_.time.time())) == ("time", "15:15:00")


def test_no_entry_after_eleven_and_no_range_without_three_bars():
    late = [100] * 18 + [105]  # breakout bar closes at 11:05
    assert orb_alerts("ABC", full_day(late)) == []
    assert orb_alerts("ABC", session([100, 101])) == []


def test_prefix_never_changes_earlier_alerts():
    rng = np.random.default_rng(3)
    bars = session(100 * np.exp(np.cumsum(rng.normal(0, .003, 75))))
    full = orb_alerts("ABC", bars)
    for n in range(1, 76):
        prefix = orb_alerts("ABC", bars.iloc[:n])
        assert prefix == full[:len(prefix)]


def test_final_closes_short_sessions_and_one_session_only():
    short = session([100, 101, 99, 102, 102])
    assert len(orb_alerts("ABC", short)) == 1
    assert orb_alerts("ABC", short, final=True)[1].reason == "data_end"
    two = pd.concat([session([100] * 3), session([100] * 3, day=DAY + pd.Timedelta(days=1))])
    with pytest.raises(ValueError):
        orb_alerts("ABC", two)


def test_completed_drops_forming_bar():
    bars = session([100, 101, 102])
    assert len(completed(bars, DAY + pd.Timedelta(minutes=567))) == 2


def test_trades_charge_indian_costs_and_scorecard_waits_for_evidence():
    table = load_rates("zerodha")
    prices = full_day([100, 102, 104, 110])
    book = trades(orb_alerts("ABC", prices), table)
    trade = book.iloc[0]
    assert trade.qty == int(40_000 // trade.entry)
    assert trade.costs > 0 and trade.net == pytest.approx(trade.gross - trade.costs)
    baseline = random_entries(prices, book, table, runs=50)
    assert baseline.shape == (50,)
    assert summarise(book, baseline, 1)["verdict"] == "CAN'T TELL"


def test_replay_and_pairs_across_symbols():
    prices = pd.concat([full_day([102]), full_day([102]).assign(symbol="XYZ")])
    alerts = replay(prices)
    assert [(a.symbol, a.side) for a in alerts][:2] == [("ABC", "BUY"), ("XYZ", "BUY")]
    assert len(trades(alerts, load_rates("zerodha"))) == 2


class FakeFeed:
    def __init__(self, bars):
        self.bars_ = bars

    def bars(self, symbol, now):
        if symbol == "BAD":
            raise RuntimeError("payload with SECRET")
        return completed(self.bars_, now)


def test_run_live_sends_each_alert_once_logs_and_saves(tmp_path):
    clock = [DAY + pd.Timedelta(hours=9, minutes=20)]
    sent = []

    class Notes:
        def send(self, text):
            sent.append(text)

    def sleep(seconds):
        clock[0] += pd.Timedelta(seconds=seconds)

    run_live(FakeFeed(full_day([102, 98.5])), ["ABC", "BAD"], Notes(),
             now=lambda: clock[0], sleep=sleep, directory=tmp_path)
    trades_sent = [s for s in sent if s.startswith("PAPER")]
    assert len(trades_sent) == 2 and trades_sent[0].startswith("PAPER BUY ABC")
    assert all("SECRET" not in s for s in sent)
    alerts, bars = load_history(tmp_path)
    assert [a.side for a in alerts] == ["BUY", "SELL"] and set(bars["symbol"]) == {"ABC"}


def test_late_start_marks_old_alerts(tmp_path):
    clock = [DAY + pd.Timedelta(hours=13)]
    sent = []

    class Notes:
        def send(self, text):
            sent.append(text)

    def sleep(seconds):
        clock[0] += pd.Timedelta(seconds=seconds)

    run_live(FakeFeed(full_day([102])), ["ABC"], Notes(), now=lambda: clock[0], sleep=sleep, directory=tmp_path)
    assert sent[0].startswith("LATE PAPER BUY")


def test_telegram_requires_private_config_and_hides_token(tmp_path):
    path = tmp_path / "telegram.json"
    path.write_text(json.dumps({"bot_token": "TOKEN123", "chat_id": "42"}))
    path.chmod(0o644)
    with pytest.raises(TelegramError):
        TelegramNotifier(path)
    path.chmod(0o600)
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(500, text="TOKEN123 echoed")

    notifier = TelegramNotifier(path, transport=httpx.MockTransport(handler))
    with pytest.raises(TelegramError) as error:
        notifier.send("hello")
    assert seen == [{"chat_id": "42", "text": "hello"}] and "TOKEN123" not in str(error.value)


def test_format_alert_says_paper():
    buy = orb_alerts("ABC", full_day([102]))[0]
    assert "PAPER BUY ABC" in format_alert(buy) and "not advice" in format_alert(buy)


def test_upstox_intraday_sorts_newest_first_payload(tmp_path):
    token = tmp_path / "token"
    token.write_text("SECRET123")
    token.chmod(0o600)
    payload = {"status": "success", "data": {"candles": [
        ["2025-03-03T09:20:00+05:30", 2, 3, 1, 2.5, 10, 0],
        ["2025-03-03T09:15:00+05:30", 1, 2, .5, 1.5, 10, 0]]}}
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, json=payload)

    client = UpstoxClient(token, transport=httpx.MockTransport(handler), cache=False)
    frame = client.intraday("NSE_EQ|INE002A01018", "minutes", 5)
    assert urls == ["https://api.upstox.com/v3/historical-candle/intraday/NSE_EQ%7CINE002A01018/minutes/5"]
    assert frame.index.is_monotonic_increasing and list(frame["close"]) == [1.5, 2.5]


def test_cli_replay_random_fails_and_planted_passes(tmp_path, capsys):
    assert main(["alerts", "replay", "--days", "60", "--out", str(tmp_path / "a.html")]) == 0
    assert capsys.readouterr().out.startswith("FAIL")
    assert main(["alerts", "replay", "--days", "60", "--pattern", "planted_orb",
                 "--out", str(tmp_path / "b.html")]) == 0
    assert capsys.readouterr().out.startswith("PASS")
    page = (tmp_path / "b.html").read_text()
    assert "PAPER BUY" in page and "http" not in page.lower()
