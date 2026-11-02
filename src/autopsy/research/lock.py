"""An exclusive-create lock and durable, append-only opening journal.

Windows are [locked_start, locked_end). data_hash identifies the locked price
snapshot (including its expected-bar schedule), not the development snapshot.
"""

from dataclasses import asdict
from pathlib import Path

import pandas as pd

from autopsy.research.trials import GENESIS, TrialLog, _append, _digest, _journal, _line_hash, _read, data_path
from autopsy.research.walkforward import Pick, RULE, _time
from autopsy.strategies import registry_hash as current_registry_hash


def hash_prices(prices):
    columns = ["symbol", "open", "high", "low", "close", "volume"]
    if "share_multiplier" in prices:
        columns.append("share_multiplier")
    # Explicit schema, timestamps and values; no pandas-version-dependent hash.
    return _digest({"columns": columns, "index": [time.isoformat() for time in prices.index],
                    "values": prices[columns].values.tolist(),
                    "expected_bars": prices.attrs.get("expected_bars"),
                    "events": prices.attrs.get("events"),
                    "bar_interval": prices.attrs.get("bar_interval")})


class Lock:
    def __init__(self, path, header):
        self.path = Path(path)
        self._header = header
        self.locked_start = _time(header["locked_start"])
        self.locked_end = _time(header["locked_end"])
        self.selection_rule = header["selection_rule"]

    @classmethod
    def create(cls, path=None, data_hash=None, registry_hash=None, picks=(), trial_log_head=None,
               locked_start=None, locked_end=None, *, trial_log_path=None):
        if locked_end is None:
            raise ValueError("locked_end is required (exclusive)")
        end = _time(locked_end)
        start = _time(locked_start) if locked_start is not None else end - pd.DateOffset(months=12)
        if start >= end:
            raise ValueError("locked_start must precede locked_end")
        if isinstance(picks, Pick):
            picks = [picks]
        picks = list(picks)
        if not picks or len({pick.mode for pick in picks}) != len(picks):
            raise ValueError("exactly one pick per selected mode required")
        if any(pick.rule != RULE for pick in picks):
            raise ValueError("unsupported selection rule")
        paths = {pick.trial_log_path for pick in picks if pick.trial_log_path is not None}
        if trial_log_path is None and len(paths) > 1:
            raise ValueError("picks must share a lifetime trial log")
        log = TrialLog(trial_log_path or next(iter(paths), None))
        if not log.path.exists() or not log.verify() or log.head != trial_log_head:
            raise ValueError("trial log head does not match verified history")
        if not data_hash or registry_hash != current_registry_hash():
            raise ValueError("data hash and current registry hash required")
        header = {"kind": "lock", "data_hash": data_hash, "registry_hash": registry_hash,
                  "picks": [asdict(pick) for pick in picks], "selection_rule": RULE,
                  "trial_log_head": trial_log_head, "trial_log_path": str(log.path.resolve()),
                  "trial_count": log.trial_count, "locked_start": start.isoformat(),
                  "locked_end": end.isoformat()}
        path = Path(path).expanduser() if path is not None else data_path("lock.jsonl")
        with _journal(path, exclusive=True) as stream:
            header = _append(stream, header, GENESIS)
        return cls(path, header)

    @classmethod
    def open(cls, path=None):
        path = Path(path).expanduser() if path is not None else data_path("lock.jsonl")
        if not path.exists():
            raise FileNotFoundError(path)
        with _journal(path) as stream:
            rows = _read(stream)
            if not rows or rows[0].get("kind") != "lock":
                raise ValueError("invalid lock journal")
            _append(stream, {"kind": "opening", "number": len(rows)}, _line_hash(rows[-1]))
        return cls(path, rows[0])

    def _rows(self):
        with self.path.open(encoding="utf-8") as stream:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_SH)
            rows = _read(stream)
        if not rows or rows[0] != self._header:
            raise ValueError("lock header changed")
        if any(row.get("kind") != "opening" or row.get("number") != number
               for number, row in enumerate(rows[1:], 1)):
            raise ValueError("invalid opening record")
        return rows

    @property
    def openings(self):
        return len(self._rows()) - 1

    @property
    def trial_count(self):
        return self._header["trial_count"]

    def verify(self):
        try:
            self._rows()
            log = TrialLog(self._header["trial_log_path"])
            # Subsequent trials are allowed; the sealed prefix must still exist.
            rows = log.rows()
            return (self._header["registry_hash"] == current_registry_hash()
                    and any(_line_hash(row) == self._header["trial_log_head"] for row in rows))
        except (OSError, ValueError, KeyError):
            return False

    def matches(self, pick, prices):
        return (asdict(pick) in self._header["picks"]
                and hash_prices(prices) == self._header["data_hash"])
