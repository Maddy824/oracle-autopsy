"""Compare a foreign engine's reported equity with independent fill accounting."""

from math import isfinite

import numpy as np

from autopsy.checks import CheckResult
from autopsy.ledger import replay
from autopsy.types import RunRecord


def check_ledger(record: RunRecord, tol: float = 0.01) -> CheckResult:
    """Audit every price timestamp with an absolute tolerance in rupees.

    ``first_bad_bar`` is zero-based in chronological order; ``gap`` is reported
    minus reference equity. Missing/extra/duplicate observations cannot support
    a verdict. Nonfinite reported values fail. A flat-price round trip is
    covered by the same identity: closing cash must equal starting cash less
    fees (and any execution-price slippage). No fills are inferred or repaired.
    """
    if not isfinite(tol) or tol < 0:
        raise ValueError("tol must be finite and nonnegative")
    reference = replay(record.fills, record.prices, record.start_cash)
    reported = record.reported_equity.sort_index(kind="stable")
    if reference.empty or not reported.index.equals(reference.index):
        return CheckResult("ledger", "CAN'T TELL", {
            "reason": "reported equity must cover every price timestamp exactly once",
        })
    gaps = reported.to_numpy(dtype=float) - reference.equity.to_numpy()
    bad = np.flatnonzero(~np.isfinite(gaps) | (np.abs(gaps) > tol))
    if not len(bad):
        return CheckResult("ledger", "PASS", {"bars_checked": len(reference)})
    bar = int(bad[0])
    time = reference.index[bar]
    previous = reference.index[bar - 1] if bar else None
    return CheckResult("ledger", "FAIL", {
        "first_bad_bar": bar,
        "first_bad_time": time.isoformat(),
        "gap": float(gaps[bar]),
        "reported_equity": float(reported.iloc[bar]),
        "reference_equity": float(reference.equity.iloc[bar]),
        "fills_since_previous_bar": [
            fill for fill in record.fills
            if fill.time <= time and (previous is None or fill.time > previous)
        ],
    })
