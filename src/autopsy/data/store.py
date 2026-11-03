"""Separate raw/adjusted Parquet snapshots with verified SHA-256 sidecars."""

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
    try:
        frame.to_parquet(temp, engine="pyarrow", index=True)
        meta = {"sha256": hashlib.sha256(temp.read_bytes()).hexdigest(),
                "source": source, "kind": kind,
                "downloaded_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat()}
        meta_temp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
        meta_temp.replace(sidecar)
    finally:
        temp.unlink(missing_ok=True)
        meta_temp.unlink(missing_ok=True)
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
    if "expected_bars" not in frame.attrs:
        if "bar_interval" not in frame.attrs:
            raise ValueError("snapshot has no expected session schedule")
        frame = with_schedule(frame, frame.attrs["bar_interval"])
    return frame, meta
