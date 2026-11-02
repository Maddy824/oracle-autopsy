"""Dated NSE cash-equity costs, in rupees, per executed order.

Rates are fractions of turnover (0.03% is 0.0003), not percentages.
IPFT is a disclosure within exchange charges. DP amounts already include GST.
No contract-note rounding, slippage, income tax or account fees are applied.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from math import isfinite
from pathlib import Path
from types import MappingProxyType


RATES_DIR = Path(__file__).with_name("rates")
_SEGMENTS = ("intraday_equity", "delivery_equity")
_RATE_FIELDS = (
    "brokerage_rate", "brokerage_cap", "stt_buy", "stt_sell",
    "exchange_rate", "sebi_rate", "ipft_rate", "gst_rate",
    "stamp_buy", "stamp_sell", "dp_sell",
)


@dataclass(frozen=True)
class RateTable:
    broker: str
    source_url: str
    accessed: str
    segment_rates: Mapping[str, Mapping[str, float]]

    def __post_init__(self) -> None:
        if not isinstance(self.broker, str) or not self.broker.strip():
            raise ValueError("broker must be nonempty")
        if not isinstance(self.source_url, str) or not self.source_url.startswith("https://"):
            raise ValueError("source_url must be an HTTPS URL")
        if date.fromisoformat(self.accessed).isoformat() != self.accessed:
            raise ValueError("accessed must be an ISO date")
        verified = {}
        for segment in _SEGMENTS:
            rates = self.segment_rates.get(segment, {})
            values = {}
            for field in _RATE_FIELDS:
                value = rates.get(field)
                if value is None:
                    raise ValueError(f"unverified rate: {segment}.{field}")
                if (
                    isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isfinite(value) or value < 0
                ):
                    raise ValueError(f"invalid rate: {segment}.{field}")
                values[field] = value
            if values["ipft_rate"] > values["exchange_rate"]:
                raise ValueError(f"IPFT exceeds exchange rate: {segment}")
            verified[segment] = MappingProxyType(values)
        object.__setattr__(self, "segment_rates", MappingProxyType(verified))


@dataclass(frozen=True)
class CostBreakdown:
    brokerage: float
    stt: float
    exchange: float
    sebi: float
    ipft: float
    gst: float
    stamp: float
    dp: float
    total: float


def load_rates(broker: str) -> RateTable:
    """Load the newest dated snapshot; never fall back from unverified rates."""
    if not isinstance(broker, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", broker):
        raise ValueError("invalid broker")
    candidates = []
    for path in RATES_DIR.glob(f"{broker}_*.json"):
        snapshot_date = path.stem.removeprefix(f"{broker}_")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", snapshot_date):
            candidates.append((date.fromisoformat(snapshot_date), path))
    if not candidates:
        raise ValueError(f"no rate table for broker: {broker}")
    snapshot_date, path = max(candidates)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["broker"] != broker or data["accessed"] != snapshot_date.isoformat():
        raise ValueError("rate table metadata does not match filename")
    return RateTable(**{field: data[field] for field in (
        "broker", "source_url", "accessed", "segment_rates",
    )})


def trade_costs(
    side: str, notional: float, segment: str, table: RateTable,
    symbol_sold_today: bool = False,
) -> CostBreakdown:
    """Price one executed order, preserving fractional paise.

    The caller tracks whether this symbol was already sold on this trading
    day, and resets that flag for each new day/symbol. Only the first delivery
    sale incurs DP. These tables cover ordinary NSE equities, not ETF-specific
    exemptions, BSE, MTF or derivatives.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    if segment not in _SEGMENTS:
        raise ValueError(f"unsupported segment: {segment}")
    if (
        isinstance(notional, bool) or not isinstance(notional, (int, float))
        or not isfinite(notional) or notional <= 0
    ):
        raise ValueError("notional must be finite and positive")
    if not isinstance(symbol_sold_today, bool):
        raise ValueError("symbol_sold_today must be a bool")
    rates = {key: Decimal(str(value)) for key, value in table.segment_rates[segment].items()}
    turnover = Decimal(str(notional))
    brokerage = min(rates["brokerage_cap"], turnover * rates["brokerage_rate"])
    stt = turnover * rates[f"stt_{side.lower()}"]
    exchange = turnover * rates["exchange_rate"]
    sebi = turnover * rates["sebi_rate"]
    ipft = turnover * rates["ipft_rate"]
    gst = rates["gst_rate"] * (brokerage + exchange + sebi)
    stamp = turnover * rates[f"stamp_{side.lower()}"]
    dp = (
        rates["dp_sell"]
        if segment == "delivery_equity" and side == "SELL" and not symbol_sold_today
        else Decimal(0)
    )
    total = brokerage + stt + exchange + sebi + gst + stamp + dp
    return CostBreakdown(*(float(value) for value in (
        brokerage, stt, exchange, sebi, ipft, gst, stamp, dp, total,
    )))
