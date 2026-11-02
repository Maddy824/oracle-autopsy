import json
from datetime import date
from pathlib import Path

import pytest

from autopsy import costs
from autopsy.costs import load_rates, trade_costs


RATES_DIR = Path(__file__).parents[1] / "src/autopsy/rates"
RATE_FIELDS = (
    "brokerage_rate", "brokerage_cap", "stt_buy", "stt_sell",
    "exchange_rate", "sebi_rate", "ipft_rate", "gst_rate",
    "stamp_buy", "stamp_sell", "dp_sell",
)


@pytest.fixture
def zerodha():
    return load_rates("zerodha")


def test_intraday_round_trip_100k(zerodha):
    buy = trade_costs("BUY", 100_000, "intraday_equity", zerodha)
    sell = trade_costs("SELL", 100_000, "intraday_equity", zerodha)
    assert buy.total + sell.total == pytest.approx(82.6812, abs=0.0001)
    for field, expected in dict(
        brokerage=40, stt=25, exchange=6.14, sebi=0.2,
        ipft=0.0002, gst=8.3412, stamp=3, dp=0,
    ).items():
        assert getattr(buy, field) + getattr(sell, field) == pytest.approx(expected)
    assert buy.stt == sell.stamp == 0


def test_delivery_round_trip_100k(zerodha):
    buy = trade_costs("BUY", 100_000, "delivery_equity", zerodha)
    sell = trade_costs("SELL", 100_000, "delivery_equity", zerodha)
    assert buy.total + sell.total == pytest.approx(237.8212, abs=0.0001)
    for field, expected in dict(
        brokerage=0, stt=200, exchange=6.14, sebi=0.2,
        ipft=0.0002, gst=1.1412, stamp=15, dp=15.34,
    ).items():
        assert getattr(buy, field) + getattr(sell, field) == pytest.approx(expected)
    assert buy.stt == sell.stt == 100
    assert buy.dp == sell.stamp == 0


def test_every_table_has_source_and_date():
    paths = list(RATES_DIR.glob("*.json"))
    assert {p.name.split("_")[0] for p in paths} == {"zerodha", "upstox"}
    for path in paths:
        table = json.loads(path.read_text())
        assert table["source_url"].startswith("https://")
        assert date.fromisoformat(table["accessed"]).isoformat() == table["accessed"]
        assert set(table["segment_rates"]) == {"intraday_equity", "delivery_equity"}


@pytest.mark.parametrize("notional,expected", [(1000, 0.3), (50_000, 15), (100_000, 20)])
def test_brokerage_cap_per_order(zerodha, notional, expected):
    assert trade_costs("BUY", notional, "intraday_equity", zerodha).brokerage == expected


def test_dp_only_first_delivery_sale_of_symbol_per_day(zerodha):
    first = trade_costs("SELL", 1000, "delivery_equity", zerodha)
    later = trade_costs("SELL", 1000, "delivery_equity", zerodha, symbol_sold_today=True)
    assert first.dp == 15.34
    assert later.dp == 0
    assert first.total - later.total == pytest.approx(15.34)
    assert trade_costs("SELL", 1000, "intraday_equity", zerodha).dp == 0


def test_ipft_is_disclosed_but_never_added_twice(zerodha):
    cost = trade_costs("SELL", 10_000_000, "intraday_equity", zerodha)
    assert cost.exchange == 307
    assert cost.ipft == 0.01
    assert cost.gst == pytest.approx(60.66)
    assert cost.total == pytest.approx(2897.66)


@pytest.mark.parametrize("notional", [0, -1, float("nan"), float("inf"), True])
def test_invalid_notional_rejected(zerodha, notional):
    with pytest.raises(ValueError, match="notional"):
        trade_costs("BUY", notional, "intraday_equity", zerodha)


@pytest.mark.parametrize("side,segment", [("HOLD", "intraday_equity"), ("BUY", "futures")])
def test_unsupported_trade_rejected(zerodha, side, segment):
    with pytest.raises(ValueError):
        trade_costs(side, 1000, segment, zerodha)


def write_table(tmp_path, accessed="2026-11-02"):
    data = json.loads((RATES_DIR / "zerodha_2026-11-02.json").read_text())
    data["accessed"] = accessed
    path = tmp_path / f"zerodha_{accessed}.json"
    path.write_text(json.dumps(data))
    return data, path


@pytest.mark.parametrize("field", RATE_FIELDS)
def test_null_rate_rejected(monkeypatch, tmp_path, field):
    data, path = write_table(tmp_path)
    data["segment_rates"]["delivery_equity"][field] = None
    path.write_text(json.dumps(data))
    monkeypatch.setattr(costs, "RATES_DIR", tmp_path)
    with pytest.raises(ValueError) as error:
        load_rates("zerodha")
    assert str(error.value) == f"unverified rate: delivery_equity.{field}"


def test_missing_rate_rejected(monkeypatch, tmp_path):
    data, path = write_table(tmp_path)
    del data["segment_rates"]["intraday_equity"]["stt_sell"]
    path.write_text(json.dumps(data))
    monkeypatch.setattr(costs, "RATES_DIR", tmp_path)
    with pytest.raises(ValueError, match=r"^unverified rate: intraday_equity.stt_sell$"):
        load_rates("zerodha")


def test_newest_table_selected_without_fallback(monkeypatch, tmp_path):
    write_table(tmp_path, "2025-12-31")
    data, path = write_table(tmp_path)
    data["segment_rates"]["intraday_equity"]["brokerage_cap"] = 25
    path.write_text(json.dumps(data))
    monkeypatch.setattr(costs, "RATES_DIR", tmp_path)
    table = load_rates("zerodha")
    assert table.accessed == "2026-11-02"
    assert trade_costs("BUY", 100_000, "intraday_equity", table).brokerage == 25
    data["segment_rates"]["intraday_equity"]["brokerage_cap"] = None
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="unverified rate"):
        load_rates("zerodha")


def test_unknown_broker_rejected():
    with pytest.raises(ValueError, match="broker"):
        load_rates("unknown")


def test_upstox_unconfirmed_delivery_percentage_cap_fails_closed():
    with pytest.raises(ValueError) as error:
        load_rates("upstox")
    assert str(error.value) == "unverified rate: delivery_equity.brokerage_rate"
