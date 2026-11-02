"""Immutable event evidence and a private, append-only event ledger.

Optional annotations must be verified from the original disclosure: an
earnings change is a signed comparable-period percentage (not price momentum),
scheduled_for is the announced meeting/results date, and side is BUY/SELL.
Missing ISINs remain empty; symbol fallback dedup cannot merge exchanges.
Documents are stored as bytes in the ledger, hex encoded in JSON. A loader
without an attachment keeps the original export row instead, explicitly
identified by document_format. Revisions never replace earlier evidence.
"""

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from math import isfinite
from pathlib import Path
from typing import Literal

import pandas as pd


def _time(value):
    value = pd.Timestamp(value)
    if pd.isna(value) or value.tz is None:
        raise ValueError("event timestamps must be valid and tz-aware")
    return value.tz_convert("Asia/Kolkata")


@dataclass(frozen=True)
class Event:
    isin: str
    symbol: str
    kind: Literal["results", "board_meeting", "bulk_deal", "block_deal"]
    source: str
    disseminated_at: pd.Timestamp | None
    first_seen_at: pd.Timestamp
    doc_hash: str
    revision: int
    scheduled_for: date | None = None
    earnings_change: float | None = None
    side: Literal["BUY", "SELL"] | None = None
    document: bytes = b""
    document_format: str = "attachment"

    def __post_init__(self):
        if self.kind not in {"results", "board_meeting", "bulk_deal", "block_deal"}:
            raise ValueError("unknown event kind")
        if not all(isinstance(v, str) and v.strip() for v in (self.symbol, self.source, self.doc_hash)):
            raise ValueError("symbol, source and doc_hash are required")
        if not isinstance(self.isin, str):
            raise ValueError("isin must be a string (empty if unavailable)")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise ValueError("revision must be a nonnegative integer")
        if self.side not in (None, "BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if self.earnings_change is not None and not isfinite(self.earnings_change):
            raise ValueError("earnings_change must be finite")
        if self.scheduled_for is not None and type(self.scheduled_for) is not date:
            raise ValueError("scheduled_for must be a date")
        if not isinstance(self.document, bytes):
            raise ValueError("document must be bytes")
        if self.document and hashlib.sha256(self.document).hexdigest() != self.doc_hash:
            raise ValueError("document hash mismatch")
        for name in ("disseminated_at", "first_seen_at"):
            value = getattr(self, name)
            if value is not None or name == "first_seen_at":
                object.__setattr__(self, name, _time(value))

    @property
    def dedup_key(self):
        return (self.isin or f"symbol:{self.symbol}", self.kind,
                self.disseminated_at.date() if self.disseminated_at is not None else None,
                self.doc_hash)


def _encode(event):
    row = asdict(event)
    for name in ("disseminated_at", "first_seen_at", "scheduled_for"):
        row[name] = row[name].isoformat() if row[name] is not None else None
    row["document"] = event.document.hex()
    return row


def _decode(row):
    row = dict(row)
    row["document"] = bytes.fromhex(row.get("document", ""))
    if row.get("scheduled_for") is not None:
        row["scheduled_for"] = date.fromisoformat(row["scheduled_for"])
    return Event(**row)


def with_events(prices, events):
    """Attach a deterministic JSON snapshot without losing expected_bars.

    An explicitly empty ledger means no notices. An absent ledger means news
    coverage is unknown. Attaching evidence does not certify archive coverage.
    """
    result = prices.copy()
    rows = sorted((_encode(event) for event in events), key=lambda row: json.dumps(row, sort_keys=True))
    result.attrs["events"] = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return result


def events_from_prices(prices):
    return [_decode(row) for row in json.loads(prices.attrs.get("events", "[]"))]


class EventLedger:
    def __init__(self, path=None):
        from autopsy.research.trials import data_path
        self.path = Path(path).expanduser() if path is not None else data_path("events.jsonl")

    def add(self, event):
        """Return False for duplicates, retaining the first imported evidence."""
        from autopsy.research.trials import GENESIS, _append, _journal, _line_hash, _read
        with _journal(self.path) as stream:
            rows = _read(stream)
            if any(_decode(row["event"]).dedup_key == event.dedup_key for row in rows):
                return False
            _append(stream, {"event": _encode(event)}, _line_hash(rows[-1]) if rows else GENESIS)
        return True

    def events(self):
        from autopsy.research.trials import _journal, _read
        if not self.path.exists():
            return []
        with _journal(self.path) as stream:
            return [_decode(row["event"]) for row in _read(stream)]
