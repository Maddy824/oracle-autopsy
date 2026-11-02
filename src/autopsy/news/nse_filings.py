"""Parse owner-downloaded NSE CSVs only; never fetch NSE or attachments.

Layout references (web search, 2026-11-02; no NSE requests):
https://www.nseindia.com/companies-listing/corporate-filings-announcements
  SYMBOL, COMPANY NAME, SUBJECT, DETAILS, ATTACHMENT, XBRL,
  BROADCAST DATE/TIME; Exchange Received Time, Exchange Dissemination Time,
  Time Taken. Only the explicit dissemination field is an availability clock;
  broadcast/received values are retained in the original row, never substituted.
https://www.nseindia.com/report-detail/display-bulk-and-block-deals
  Date, Symbol, Security Name, Client Name, Buy / Sell, Quantity Traded,
  Trade Price / Wght. Avg. Price, Remarks (optional for block exports).
https://www.nseindia.com/market-data/large-deals
  Daily layout aliases: BUY/SELL, Volume, TRADE PRICE/ WEIGHTED. AVG. PRICE.
  Trade Date is NOT dissemination time. Deal imports default to None.

Headers tolerate BOM, whitespace, case and punctuation. NSE's timezone-less
CSV clock is explicitly interpreted as IST here only. Date-only values are
missing times. ISIN, earnings change and scheduled dates are not guaranteed
export columns: supply verified isin_by_symbol and annotations by attachment
URL. annotations may contain earnings_change, scheduled_for and revision.
documents maps attachment URLs to manually saved local files; their exact
bytes are retained and hashed. Without those, retain/hash the export row as
export_row (not an attachment hash). No text sentiment or buyer inference.
"""

import csv
import hashlib
import json
from pathlib import Path
import re

import pandas as pd

from autopsy.news.events import Event, _time


def _key(value):
    return re.sub(r"[^a-z0-9]", "", value.lower().lstrip("\ufeff"))


def _rows(paths):
    for path in paths:
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or "symbol" not in {_key(k) for k in reader.fieldnames}:
                raise ValueError("NSE CSV requires Symbol column")
            for original in reader:
                if None in original:
                    raise ValueError("malformed NSE CSV row")
                row = {_key(k): (v or "").strip() for k, v in original.items()}
                yield row, json.dumps(original, sort_keys=True, separators=(",", ":")).encode()


def _disseminated(row):
    value = next((row[k] for k in ("exchangedisseminationtime", "disseminationdatetime",
                                  "disseminationtime") if row.get(k)), "")
    if not re.search(r"\d{1,2}:\d{2}", value):
        return None
    parsed = pd.to_datetime(value, dayfirst=True)
    return parsed.tz_localize("Asia/Kolkata") if parsed.tz is None else _time(parsed)


def load_nse_announcements(csv_paths, *, isin_by_symbol=None, first_seen_at=None,
                           documents=None, annotations=None):
    """Import only results and board-meeting rows; preserve missing timestamps."""
    seen = _time(first_seen_at) if first_seen_at is not None else pd.Timestamp.now(tz="Asia/Kolkata")
    events = []
    for row, original in _rows(csv_paths):
        subject = row.get("subject", "").lower()
        details = row.get("details", "").lower()
        # An outcome containing actual results is a result; an advance meeting
        # intimation to consider results is still only a board-meeting notice.
        if "board meeting" in subject and "outcome" not in subject:
            kind = "board_meeting"
        elif "financial results" in subject or "financial results" in details or subject == "results":
            kind = "results"
        elif "board meeting" in subject:
            kind = "board_meeting"
        else:
            continue
        attachment = row.get("attachment", "")
        local = (documents or {}).get(attachment)
        document = Path(local).read_bytes() if local is not None else original
        extra = dict((annotations or {}).get(attachment, {}))
        revision = extra.pop("revision", 0)
        events.append(Event(
            (isin_by_symbol or {}).get(row["symbol"], row.get("isin", "")), row["symbol"], kind,
            "NSE", _disseminated(row), seen, hashlib.sha256(document).hexdigest(), revision,
            document=document, document_format="attachment" if local is not None else "export_row", **extra))
    return events


def load_nse_deals(csv_paths, *, kind, isin_by_symbol=None, first_seen_at=None, disseminated_at=None):
    """Import bulk/block buys AND sells. Optional time is verified export publication.

    Supply disseminated_at only from separate timestamped publication evidence,
    never from the trade date or an assumed end-of-day publication time.
    """
    if kind not in ("bulk_deal", "block_deal"):
        raise ValueError("deal kind must be bulk_deal or block_deal")
    seen = _time(first_seen_at) if first_seen_at is not None else pd.Timestamp.now(tz="Asia/Kolkata")
    published = _time(disseminated_at) if disseminated_at is not None else None
    events = []
    for row, original in _rows(csv_paths):
        required = {"date", "symbol", "clientname", "buysell"}
        if not required <= row.keys() or not ({"quantitytraded", "volume"} & row.keys()):
            raise ValueError("missing NSE deal columns")
        trade_date = pd.to_datetime(row["date"], dayfirst=True).date()
        if published is not None and published.date() < trade_date:
            raise ValueError("dissemination precedes deal date")
        side = {"B": "BUY", "S": "SELL", "BUY": "BUY", "SELL": "SELL"}.get(row["buysell"].upper())
        if side is None:
            raise ValueError("unknown NSE deal side")
        events.append(Event(
            (isin_by_symbol or {}).get(row["symbol"], row.get("isin", "")), row["symbol"], kind,
            "NSE", published, seen, hashlib.sha256(original).hexdigest(), 0,
            side=side, document=original, document_format="export_row"))
    return events
