"""Private, append-only research history with a SHA-256 chain.

Hashes detect edits, not malicious rewriting of the entire history. A lock
anchors the selected head; retaining the lock is part of the audit trail.
"""

from contextlib import contextmanager
from datetime import date, datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path

GENESIS = "0" * 64


def data_path(name):
    return Path(os.environ.get("AUTOPSY_DATA_DIR", "~/oracle-autopsy-data")).expanduser() / name


def _json(value):
    def encode(item):
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        if isinstance(item, Path):
            return str(item)
        raise TypeError(f"unsupported journal value: {type(item).__name__}")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=encode)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _line_hash(row):
    # The whole canonical preceding line, excluding its newline delimiter.
    return _digest(row)


@contextmanager
def _journal(path, *, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | (os.O_EXCL if exclusive else 0)
    with os.fdopen(os.open(path, flags, 0o600), "r+", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield stream
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _read(stream):
    stream.seek(0)
    rows, previous = [], GENESIS
    for line in stream:
        if not line.endswith("\n"):
            raise ValueError("broken hash chain: incomplete line")
        try:
            row = json.loads(line)
            digest = row.pop("hash")
            if row["previous_hash"] != previous or digest != _digest(row):
                raise ValueError("hash mismatch")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError("broken hash chain") from exc
        row["hash"] = digest
        if _json(row) != line.rstrip("\n"):
            raise ValueError("broken hash chain: noncanonical line")
        rows.append(row)
        previous = _line_hash(row)
    return rows


def _append(stream, payload, previous):
    row = dict(payload, previous_hash=previous, timestamp=datetime.now(timezone.utc).isoformat())
    row["hash"] = _digest(row)
    stream.seek(0, os.SEEK_END)
    stream.write(_json(row) + "\n")
    stream.flush()
    os.fsync(stream.fileno())
    return row


class TrialLog:
    def __init__(self, path=None):
        self.path = Path(path).expanduser() if path is not None else data_path("trials.jsonl")

    def append(self, strategy, params, window, metrics):
        with _journal(self.path) as stream:
            rows = _read(stream)
            row = _append(stream, {"strategy": strategy, "params": params,
                                   "window": window, "metrics": metrics},
                          _line_hash(rows[-1]) if rows else GENESIS)
            return _line_hash(row)

    def rows(self):
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_SH)
            return _read(stream)

    def verify(self):
        try:
            self.rows()
            return True
        except (ValueError, OSError):
            return False

    @property
    def head(self):
        rows = self.rows()
        return _line_hash(rows[-1]) if rows else GENESIS

    @property
    def trial_count(self):
        # Started attempts survive crashes; their completion is not a new trial.
        return sum(row["metrics"].get("status") != "complete" for row in self.rows())
