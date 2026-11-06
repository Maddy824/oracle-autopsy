import csv

import pandas as pd
import pytest

from autopsy.news.nse_filings import company_key, load_nse_financial_results

OLD = ["COMPANY NAME", "AUDITED / UNAUDITED", "PERIOD", "PERIOD ENDED", "RELATING TO",
       "Exchange Received Time", "Exchange Dissemination Time", "Time Taken"]
NEW = ["SYMBOL \n", "COMPANY NAME \n", "QUARTER END DATE \n", "TYPE OF SUBMISSION \n",
       "BROADCAST DATE/TIME \n", "REVISED DATE/TIME \n", "EXCHANGE DISSEMINATION TIME \n"]
SEEN = pd.Timestamp("2026-11-06 10:00", tz="Asia/Kolkata")


def _csv(path, header, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _old(name, period, received, disseminated):
    return [name, "Un-Audited", "Quarterly", period, "Second Quarter", received, disseminated, ""]


def _new(symbol, name, quarter, broadcast, disseminated, kind="Original"):
    return [symbol, name, quarter, kind, broadcast, "", disseminated]


def _load(tmp_path, old_rows, new_rows):
    paths = [_csv(tmp_path / "old.csv", OLD, old_rows), _csv(tmp_path / "new.csv", NEW, new_rows)]
    return load_nse_financial_results(paths, first_seen_at=SEEN)


def _by_symbol(events):
    return {(e.symbol, e.disseminated_at) for e in events}


def test_company_key_ignores_case_ampersand_and_limited():
    assert company_key("Mahindra & Mahindra Limited") == company_key("MAHINDRA AND MAHINDRA LTD")


def test_old_rows_take_symbol_from_exact_company_name(tmp_path):
    events, report = _load(
        tmp_path,
        [_old("ABC Industries Limited", "30-Sep-2015", "04-Nov-2015 14:32:25", "04-Nov-2015 14:36:03")],
        [_new("ABC", "ABC Industries Limited", "30-SEP-2025", "05-Nov-2025 15:00:00", "05-Nov-2025 15:00:20")])
    assert _by_symbol(events) == {
        ("ABC", pd.Timestamp("2015-11-04 14:36:03", tz="Asia/Kolkata")),
        ("ABC", pd.Timestamp("2025-11-05 15:00:20", tz="Asia/Kolkata")),
    }
    assert all(e.kind == "results" and e.source == "NSE" and e.first_seen_at == SEEN for e in events)
    assert report["unmapped_companies"] == [] and report["without_time"] == 0


def test_one_event_per_quarter_at_earliest_dissemination(tmp_path):
    events, report = _load(
        tmp_path,
        [_old("ABC Limited", "30-Sep-2015", "04-Nov-2015 14:32:25", "04-Nov-2015 14:40:00"),
         _old("ABC Limited", "30-Sep-2015", "04-Nov-2015 14:30:00", "04-Nov-2015 14:31:00")],
        [_new("ABC", "ABC Limited", "30-SEP-2025", "05-Nov-2025 15:00:00", "05-Nov-2025 15:00:20")])
    assert report["rows"] == 3 and report["events"] == 2
    assert ("ABC", pd.Timestamp("2015-11-04 14:31:00", tz="Asia/Kolkata")) in _by_symbol(events)


def test_late_revision_time_is_unknown_not_used(tmp_path):
    # Original filed on 5 Nov with no dissemination time; only a 20 Nov revision
    # carries one. Using 20 Nov would misdate the event, so the time is unknown.
    events, report = _load(
        tmp_path, [],
        [_new("ABC", "ABC Limited", "30-SEP-2025", "05-Nov-2025 15:00:00", ""),
         _new("ABC", "ABC Limited", "30-SEP-2025", "20-Nov-2025 10:00:00", "20-Nov-2025 10:00:30", "Revised")])
    assert len(events) == 1 and events[0].disseminated_at is None
    assert report["without_time"] == 1


def test_unknown_and_ambiguous_names_are_skipped_and_reported(tmp_path):
    events, report = _load(
        tmp_path,
        [_old("Unknown Co Limited", "30-Sep-2015", "04-Nov-2015 14:00:00", "04-Nov-2015 14:01:00"),
         _old("Twin Limited", "30-Sep-2015", "04-Nov-2015 14:00:00", "04-Nov-2015 14:01:00")],
        [_new("TWINA", "Twin Limited", "30-SEP-2025", "05-Nov-2025 15:00:00", "05-Nov-2025 15:00:20"),
         _new("TWINB", "Twin Ltd", "30-SEP-2025", "05-Nov-2025 15:00:00", "05-Nov-2025 15:00:20")])
    assert report["unmapped_companies"] == ["Twin Limited", "Unknown Co Limited"]
    assert {e.symbol for e in events} == {"TWINA", "TWINB"}


def test_missing_period_column_is_rejected(tmp_path):
    path = _csv(tmp_path / "bad.csv", ["COMPANY NAME", "Exchange Dissemination Time"],
                [["ABC Limited", "04-Nov-2015 14:36:03"]])
    with pytest.raises(ValueError, match="PERIOD ENDED"):
        load_nse_financial_results([path], first_seen_at=SEEN)
