"""Audit feature reproducibility and dependence on future observations."""

from collections.abc import Callable
from numbers import Integral

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype

from autopsy.checks import CheckResult
from autopsy.types import _ist_index


FeatureFunction = Callable[[pd.DataFrame], pd.DataFrame]


def _prices(prices: pd.DataFrame) -> pd.DataFrame:
    result = prices.copy(deep=True)
    result.index = _ist_index(result.index, "prices")
    if not result.index.is_monotonic_increasing:
        raise ValueError("prices must be ordered by timestamp")
    return result


def _features(feature_fn: FeatureFunction, prices: pd.DataFrame) -> pd.DataFrame:
    # Isolate callbacks that modify their argument or return a reusable buffer.
    result = feature_fn(prices.copy(deep=True))
    if not isinstance(result, pd.DataFrame):
        raise ValueError("feature_fn must return a DataFrame")
    if not result.columns.is_unique:
        raise ValueError("feature columns must be unique")
    return result.copy(deep=True)


def check_determinism(feature_fn: FeatureFunction, prices: pd.DataFrame) -> CheckResult:
    """Compare two independent evaluations exactly, including axes and dtypes.

    Matching missing values are equal. Random state is deliberately not reset:
    reseeding between calls would conceal a nondeterministic feature function.
    """
    prices = _prices(prices)
    first = _features(feature_fn, prices)
    second = _features(feature_fn, prices)
    if not first.equals(second):
        return CheckResult("determinism", "CAN'T TELL", {
            "reason": "feature_fn returned different output on identical input",
        })
    if first.empty:
        return CheckResult("determinism", "CAN'T TELL", {
            "reason": "no feature values to compare",
        })
    return CheckResult("determinism", "PASS", {})


def _equal_values(left: pd.Series, right: pd.Series) -> np.ndarray:
    if is_numeric_dtype(left.dtype) and is_numeric_dtype(right.dtype):
        dtype = complex if left.dtype.kind == "c" or right.dtype.kind == "c" else float
        return np.isclose(
            left.to_numpy(dtype=dtype, na_value=np.nan),
            right.to_numpy(dtype=dtype, na_value=np.nan),
            rtol=1e-9, atol=0.0, equal_nan=True,
        )
    return (left.eq(right).fillna(False) | (left.isna() & right.isna())).to_numpy(dtype=bool)


def check_lookahead(
    feature_fn: FeatureFunction,
    prices: pd.DataFrame,
    cutoffs: int = 20,
    seed: int = 0,
) -> CheckResult:
    """Compare historical features with features recomputed on inclusive cuts.

    Select up to ``cutoffs`` evenly spaced positions among distinct timestamps,
    excluding the final timestamp (which would remove no future data). Include
    every symbol's row at the cut time. ``seed`` is reserved for compatibility;
    evenly spaced cuts require no randomness and never alter RNG state.

    Numeric comparison is NaN-aware with rtol=1e-9 and atol=0; other values
    compare exactly. Evidence maps each leaking column to the earliest differing
    timestamp (ISO 8601 in IST) across the sampled cuts. PASS covers these cuts
    only. Features must preserve the input row index, including duplicate times.
    Callback errors and invalid output contracts propagate instead of passing.
    """
    if isinstance(cutoffs, bool) or not isinstance(cutoffs, Integral) or cutoffs <= 0:
        raise ValueError("cutoffs must be a positive integer")
    prices = _prices(prices)
    times = prices.index.unique()
    if len(times) < 2:
        return CheckResult("lookahead", "CAN'T TELL", {
            "reason": "at least two distinct timestamps are needed",
        })

    full = _features(feature_fn, prices)
    repeat = _features(feature_fn, prices)
    if not full.equals(repeat):
        return CheckResult("lookahead", "CAN'T TELL", {
            "reason": "feature_fn returned different output on identical input",
        })
    if not full.index.equals(prices.index):
        raise ValueError("feature_fn must preserve the input index")
    if full.empty:
        return CheckResult("lookahead", "CAN'T TELL", {
            "reason": "no feature values to compare",
        })

    selected = times[np.linspace(0, len(times) - 2, min(cutoffs, len(times) - 1), dtype=int)]
    leaks = {}
    for cutoff in selected:
        stop = prices.index.searchsorted(cutoff, side="right")
        prefix = prices.iloc[:stop]
        truncated = _features(feature_fn, prefix)
        if not truncated.index.equals(prefix.index):
            raise ValueError("feature_fn must preserve the input index")
        expected = full.iloc[:stop]
        for column in full.columns.union(truncated.columns, sort=False):
            if column not in expected or column not in truncated:
                first_difference = prefix.index[0]
            else:
                differences = np.flatnonzero(~_equal_values(expected[column], truncated[column]))
                if not len(differences):
                    continue
                first_difference = prefix.index[differences[0]]
            if column not in leaks or first_difference < leaks[column]:
                leaks[column] = first_difference

    return CheckResult("lookahead", "FAIL" if leaks else "PASS", {
        "leaking_columns": {column: time.isoformat() for column, time in leaks.items()},
        "cutoffs": [time.isoformat() for time in selected],
    })
