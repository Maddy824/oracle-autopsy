"""Separate raw/adjusted Parquet snapshots with verified SHA-256 sidecars."""

import gzip
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pandas as pd

from autopsy.data.schedule import with_schedule
from autopsy.types import _validated_prices


def data_dir():
    return Path(os.environ.get("AUTOPSY_DATA_DIR", "~/oracle-autopsy-data")).expanduser()


def _write_snapshot(df, path, kind, source):
    frame = _validated_prices(df)
    if "expected_bars" not in frame.attrs:
        if "bar_interval" not in frame.attrs:
            raise ValueError("snapshot needs expected_bars or a bar_interval session schedule")
        frame = with_schedule(frame, frame.attrs["bar_interval"])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    sidecar = path.with_suffix(".json")
    meta_temp = temp.with_suffix(".json.tmp")
    schedule = path.with_suffix(".schedule.json.gz")
    schedule_temp = temp.with_suffix(".schedule.tmp")
    try:
        # The session grid can hold millions of pairs; Parquet metadata cannot.
        stored = frame.copy(deep=False)
        stored.attrs = {key: value for key, value in frame.attrs.items() if key != "expected_bars"}
        stored.to_parquet(temp, engine="pyarrow", index=True)
        expected = frame.attrs["expected_bars"]
        payload = gzip.compress((expected if isinstance(expected, str) else json.dumps(expected)).encode(), mtime=0)
        schedule_temp.write_bytes(payload)
        meta = {"sha256": hashlib.sha256(temp.read_bytes()).hexdigest(),
                "schedule_sha256": hashlib.sha256(payload).hexdigest(),
                "source": source, "kind": kind,
                "downloaded_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat()}
        meta_temp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
        schedule_temp.replace(schedule)
        meta_temp.replace(sidecar)
    finally:
        temp.unlink(missing_ok=True)
        meta_temp.unlink(missing_ok=True)
        schedule_temp.unlink(missing_ok=True)
    return path


def save_snapshot(df, kind, source):
    if kind not in ("raw", "adjusted"):
        raise ValueError("snapshot kind must be raw or adjusted")
    return _write_snapshot(df, data_dir() / kind / f"{uuid4().hex}.parquet", kind, source)


def load_snapshot(path):
    """Verify bytes before parsing; preserve the original expected schedule."""
    path = Path(path).expanduser()
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    if hashlib.sha256(path.read_bytes()).hexdigest() != meta["sha256"]:
        raise ValueError("snapshot hash mismatch")
    frame = _validated_prices(pd.read_parquet(path, engine="pyarrow"))
    if "schedule_sha256" in meta:
        payload = path.with_suffix(".schedule.json.gz").read_bytes()
        if hashlib.sha256(payload).hexdigest() != meta["schedule_sha256"]:
            raise ValueError("snapshot schedule hash mismatch")
        frame.attrs["expected_bars"] = gzip.decompress(payload).decode()
    if "expected_bars" not in frame.attrs:
        if "bar_interval" not in frame.attrs:
            raise ValueError("snapshot has no expected session schedule")
        frame = with_schedule(frame, frame.attrs["bar_interval"])
    return frame, meta
