import numpy as np
import pandas as pd
import pytest

from autopsy.checks import CheckResult
from autopsy.checks.lookahead import check_determinism, check_lookahead


@pytest.fixture
def prices():
    return pd.DataFrame(
        {"close": 100 + np.arange(40, dtype=float) ** 2},
        index=pd.date_range("2026-01-05 09:15", periods=40, freq="5min", tz="Asia/Kolkata"),
    )


def test_shift_minus_5_leaks(prices):
    def features(frame):
        return frame.close.rolling(5).std().shift(-5).to_frame("target_volatility_5d")

    result = check_lookahead(features, prices)
    assert isinstance(result, CheckResult)
    assert result.name == "lookahead"
    assert result.verdict == "FAIL"
    assert result.evidence["leaking_columns"] == {
        "target_volatility_5d": prices.index[0].isoformat(),
    }


def test_rolling_mean_clean(prices):
    features = lambda frame: frame.close.rolling(5).mean().to_frame("mean")
    result = check_lookahead(features, prices)
    assert result.verdict == "PASS"
    assert result.evidence["leaking_columns"] == {}
    assert check_determinism(features, prices).verdict == "PASS"


def test_nondeterministic_cant_tell(prices, monkeypatch):
    # Fixed draws exercise the random-noise callback without a flaky assertion.
    draws = iter([0.1, 0.9, 0.2, 0.8])
    monkeypatch.setattr(np.random, "random", lambda: next(draws))

    def features(frame):
        return (frame.close + np.random.random()).to_frame("noisy")

    result = check_determinism(features, prices)
    assert result.name == "determinism"
    assert result.verdict == "CAN'T TELL"
    assert check_lookahead(features, prices).verdict == "CAN'T TELL"


def test_all_leaks_report_earliest_timestamp(prices):
    def features(frame):
        return pd.DataFrame({
            "next": frame.close.shift(-1),
            "global_mean": frame.close - frame.close.mean(),
            "clean": frame.close.rolling(5).mean(),
        })

    result = check_lookahead(features, prices, cutoffs=100)
    assert result.evidence["leaking_columns"] == {
        "next": prices.index[0].isoformat(),
        "global_mean": prices.index[0].isoformat(),
    }


@pytest.mark.parametrize("delta, verdict", [(5e-10, "PASS"), (2e-9, "FAIL")])
def test_relative_tolerance(prices, delta, verdict):
    def features(frame):
        return pd.DataFrame({"value": 1.0 + (delta if len(frame) < len(prices) else 0)}, index=frame.index)

    assert check_lookahead(features, prices).verdict == verdict


def test_no_absolute_tolerance_hides_near_zero_leak(prices):
    def features(frame):
        return pd.DataFrame({"value": 1e-12 if len(frame) < len(prices) else 0.0}, index=frame.index)

    assert check_lookahead(features, prices).verdict == "FAIL"


def test_determinism_detects_even_tiny_changes(prices):
    draws = iter([0.0, 1e-12])

    def features(frame):
        return (frame.close + next(draws)).to_frame("value")

    assert check_determinism(features, prices).verdict == "CAN'T TELL"


def test_cutoffs_are_even_and_keep_simultaneous_rows_together(prices):
    frame = prices.iloc[:6].loc[prices.index[:6].repeat(2)]
    seen = []

    def features(data):
        seen.append(data.index.copy())
        return data.copy()

    result = check_lookahead(features, frame, cutoffs=3, seed=99)
    assert result.verdict == "PASS"
    assert [len(index) for index in seen] == [12, 12, 2, 6, 10]
    assert result.evidence["cutoffs"] == [frame.index[i].isoformat() for i in (0, 4, 8)]


def test_mutating_callback_receives_independent_inputs(prices):
    original = prices.copy(deep=True)

    def features(frame):
        frame["close"] += 1
        return frame

    assert check_determinism(features, prices).verdict == "PASS"
    assert check_lookahead(features, prices).verdict == "PASS"
    pd.testing.assert_frame_equal(prices, original)


@pytest.mark.parametrize("length", [0, 1])
def test_insufficient_history_cant_tell(prices, length):
    assert check_lookahead(lambda frame: frame, prices.iloc[:length]).verdict == "CAN'T TELL"


@pytest.mark.parametrize("cutoffs", [0, -1, 1.5, True])
def test_invalid_cutoff_count_rejected(prices, cutoffs):
    with pytest.raises(ValueError, match="cutoffs"):
        check_lookahead(lambda frame: frame, prices, cutoffs=cutoffs)


def test_changed_feature_columns_fail(prices):
    def features(frame):
        return frame.rename(columns={"close": "future" if len(frame) == len(prices) else "past"})

    result = check_lookahead(features, prices)
    assert result.verdict == "FAIL"
    assert set(result.evidence["leaking_columns"]) == {"future", "past"}


@pytest.mark.parametrize("check", [check_lookahead, check_determinism])
def test_naive_timestamps_rejected(prices, check):
    prices.index = prices.index.tz_localize(None)
    with pytest.raises(ValueError, match="tz-aware"):
        check(lambda frame: frame, prices)
