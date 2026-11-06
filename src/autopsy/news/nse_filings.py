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


def _rows(paths, *, require_symbol=True):
    for path in paths:
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or (require_symbol and "symbol" not in {_key(k) for k in reader.fieldnames}):
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


def company_key(name):
    """Normalise an NSE company name for exact matching (case, '&', 'Limited')."""
    name = name.lower().replace("&", " and ")
    name = re.sub(r"\b(limited|ltd|the)\b", " ", name)
    return re.sub(r"[^a-z0-9]", "", name)


def _clock(value):
    if not re.search(r"\d{1,2}:\d{2}", value or ""):
        return None
    return pd.to_datetime(value, dayfirst=True).tz_localize("Asia/Kolkata")


def load_nse_financial_results(csv_paths, *, first_seen_at=None):
    """Import Financial Results and Integrated Filing - Financials exports.

    Layouts (owner downloads, 2026-11-06):
      corporate-filings-financial-results (quarters to Dec 2024): COMPANY NAME,
        ..., PERIOD ENDED, Exchange Received Time, Exchange Dissemination Time.
        No symbol column.
      corporate-integrated-filing (quarters from Mar 2025): SYMBOL, COMPANY
        NAME, QUARTER END DATE, TYPE OF SUBMISSION, BROADCAST DATE/TIME,
        REVISED DATE/TIME, EXCHANGE DISSEMINATION TIME.
    Symbols for symbol-less rows come only from exact normalised company names
    seen with a symbol in the same import; ambiguous or unknown names are
    skipped and reported. One results event per symbol and period: the
    earliest dissemination among its rows (standalone, consolidated,
    revisions). If any row was received/broadcast on an earlier date than that,
    the publication time is unknown (None), never the later revision time.
    Returns (events, report).
    """
    seen = _time(first_seen_at) if first_seen_at is not None else pd.Timestamp.now(tz="Asia/Kolkata")
    rows = list(_rows(csv_paths, require_symbol=False))
    names = {}
    for row, _ in rows:
        if row.get("symbol") and row.get("companyname"):
            names.setdefault(company_key(row["companyname"]), set()).add(row["symbol"])
    groups, unmapped = {}, set()
    for row, original in rows:
        period = row.get("periodended") or row.get("quarterenddate")
        if not period:
            raise ValueError("NSE results CSV requires PERIOD ENDED or QUARTER END DATE")
        symbol = row.get("symbol")
        if not symbol:
            candidates = names.get(company_key(row.get("companyname", "")), set())
            if len(candidates) != 1:
                unmapped.add(row.get("companyname", ""))
                continue
            symbol = next(iter(candidates))
        key = (symbol, pd.to_datetime(period, dayfirst=True).date())
        groups.setdefault(key, []).append((row, original))
    events, unknown = [], 0
    for (symbol, _), members in sorted(groups.items()):
        timed = [(_disseminated(row), row, original) for row, original in members]
        timed = [item for item in timed if item[0] is not None]
        filed = [_clock(row.get(k)) for row, _ in members
                 for k in ("exchangereceivedtime", "broadcastdatetime")]
        filed = [value for value in filed if value is not None]
        if timed:
            published, _, original = min(timed, key=lambda item: item[0])
            if filed and min(filed).date() < published.date():
                published = None
        else:
            published, original = None, members[0][1]
        unknown += published is None
        events.append(Event("", symbol, "results", "NSE", published, seen,
                            hashlib.sha256(original).hexdigest(), 0,
                            document=original, document_format="export_row"))
    report = {"rows": len(rows), "events": len(events), "without_time": unknown,
              "unmapped_companies": sorted(unmapped)}
    return events, report


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
