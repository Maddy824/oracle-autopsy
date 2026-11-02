import json
import hashlib

import pandas as pd
import pytest

from autopsy.research.lock import Lock, hash_prices
from autopsy.research.trials import TrialLog
from autopsy.research.walkforward import Pick, select, walk_forward
from autopsy.strategies import REGISTRY, Strategy, registry_hash
from synthetic_bars import opening_range_bars


def test_trial_log_tamper_detected(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPSY_DATA_DIR", str(tmp_path))
    log = TrialLog()
    for number in range(3):
        log.append("orb", {"minutes": 15}, ["a", "b"], {"net": number})
    assert log.path.parent == tmp_path
    assert log.verify()
    lines = log.path.read_text().splitlines()
    assert json.loads(lines[1])["previous_hash"] == hashlib.sha256(lines[0].encode()).hexdigest()
    row = json.loads(lines[1])
    row["metrics"]["net"] = 9000
    lines[1] = json.dumps(row)
    log.path.write_text("\n".join(lines) + "\n")
    assert not log.verify()
    with pytest.raises(ValueError, match="chain"):
        log.append("orb", {}, [], {})


def test_locked_window_never_used_in_selection(tmp_path):
    boundary = pd.Timestamp("2025-04-01", tz="Asia/Kolkata")

    class GuardedFrame(pd.DataFrame):
        @property
        def _constructor(self):
            return GuardedFrame

        def __getitem__(self, key):
            if isinstance(key, str) and (self.index >= boundary).any():
                raise AssertionError("read a holdout column")
            return super().__getitem__(key)

    bars = GuardedFrame(opening_range_bars(days=80))
    log = TrialLog(tmp_path / "trials.jsonl")
    orb = REGISTRY["orb"]
    strategy = Strategy("orb", "intraday", {"minutes": [15]}, orb.features, orb.signals)
    results = walk_forward(strategy, bars, boundary, folds=2, trial_log=log, slippage_grid=(10,))
    assert len(results) == 2
    assert all(result.end <= boundary for result in results)
    assert all(result.slippage_bps == 20 for result in results)
    pick = select(results)
    assert pick.strategy == "orb"
    assert pick.base_slippage_bps == 10
    assert log.verify() and log.trial_count == 1
    lock = Lock.create(tmp_path / "lock.jsonl", hash_prices(pd.DataFrame(bars.loc[bars.index >= boundary])),
                       registry_hash(), [pick], log.head, locked_end=boundary + pd.DateOffset(years=1),
                       trial_log_path=log.path)
    assert lock.locked_start == boundary
    assert lock.selection_rule == pick.rule
    with pytest.raises(FileExistsError):
        Lock.create(lock.path, "x", registry_hash(), [pick], log.head, locked_end=lock.locked_end)
