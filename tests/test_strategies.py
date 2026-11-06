from dataclasses import FrozenInstanceError, replace
from itertools import product
from types import MappingProxyType

import numpy as np
import pandas as pd
import pytest

import autopsy.strategies as strategies
from autopsy.checks.lookahead import check_lookahead
from autopsy.strategies import REGISTRY, registry_hash
from synthetic_bars import five_minute_bars


GRIDS = {
    "orb": {"minutes": (15, 30)},
    "vwap_revert": {"deviation": (1.0, 1.5, 2.0)},
    "first_hour_momentum": {"threshold": (0.5, 1.0)},
    "gap_play": {"gap": (1, 2), "mode": ("fade", "continue")},
    "nday_breakout": {"n": (20, 55)},
    "trend_pullback": {"ma": (50, 100), "pullback": (3, 5)},
    "short_reversal": {"lookback": (3, 5)},
}
VARIANTS = [
    (name, dict(zip(grid, values)))
    for name, grid in GRIDS.items() for values in product(*grid.values())
]


def test_registry_frozen():
    # Task 10 adds three event rules plus intraday results-filter trials.
    assert set(REGISTRY) == set(GRIDS) | {
        "earnings_continuation", "earnings_reaction", "weekly_loser_reversal", "monthly_momentum", "post_results_orb", "block_buy_continuation",
        "orb+results_filter", "vwap_revert+results_filter", "first_hour_momentum+results_filter",
        "gap_play+results_filter", "post_results_orb+results_filter",
    }
    counts = {"intraday": 0, "swing": 0}
    for name in GRIDS:
        strategy = REGISTRY[name]
        assert strategy.name == name
        assert dict(strategy.params_grid) == GRIDS[name]
        counts[strategy.mode] += np.prod([len(values) for values in strategy.params_grid.values()])
    assert counts == {"intraday": 11, "swing": 8}
    with pytest.raises(TypeError):
        REGISTRY["extra"] = REGISTRY["orb"]
    with pytest.raises(FrozenInstanceError):
        REGISTRY["orb"].name = "changed"
    with pytest.raises(TypeError):
        REGISTRY["orb"].params_grid["minutes"] = (10,)
    with pytest.raises(TypeError):
        REGISTRY["orb"].params_grid["minutes"][0] = 10


@pytest.mark.parametrize("name,params", VARIANTS)
def test_every_strategy_passes_lookahead(name, params):
    prices = five_minute_bars(60, symbols=("ALPHA", "BETA"))
    strategy = REGISTRY[name]
    result = check_lookahead(lambda frame: strategy.features(frame, params), prices)
    assert result.verdict == "PASS", result.evidence
    features = strategy.features(prices, params)
    full = strategy.signals(prices, features, params)
    for cutoff in (prices.index[25], prices.index[451], prices.index[6000]):
        prefix = prices.loc[:cutoff]
        assert strategy.signals(prefix, strategy.features(prefix, params), params) == [
            signal for signal in full if signal.time <= cutoff
        ]
    assert all(signal.target in ((0, 1) if strategy.mode == "swing" else (-1, 0, 1)) for signal in full)


@pytest.mark.parametrize("minutes", [15, 30])
@pytest.mark.parametrize("direction", [-1, 1])
def test_orb_signal_after_range(minutes, direction):
    prices = five_minute_bars(1)
    prices.loc[:, ["open", "close"]] = 100.0
    prices.loc[:, "high"] = 101.0
    prices.loc[:, "low"] = 99.0
    boundary = prices.index[0] + pd.Timedelta(minutes=minutes)
    prices.loc[boundary:, "close"] = 100 + 2 * direction
    prices.loc[boundary:, "high"] = 103.0
    prices.loc[boundary:, "low"] = 97.0
    strategy, params = REGISTRY["orb"], {"minutes": minutes}
    features = strategy.features(prices, params)
    signals = strategy.signals(prices, features, params)
    assert [(s.time, s.target) for s in signals] == [(boundary + pd.Timedelta(minutes=5), direction)]
    assert features.loc[boundary, "range_high"] == 101.0
    assert features.loc[boundary, "range_low"] == 99.0
    # A missing opening bar must not turn a partial range into a complete one.
    incomplete = prices.drop(prices.index[1])
    assert strategy.signals(incomplete, strategy.features(incomplete, params), params) == []


def test_registry_hash_changes_on_grid_edit(monkeypatch):
    original = registry_hash()
    assert len(original) == 64
    assert int(original, 16) >= 0
    assert registry_hash() == original
    changed = dict(REGISTRY)
    changed["orb"] = replace(changed["orb"], params_grid={"minutes": [15, 45]})
    monkeypatch.setattr(strategies, "REGISTRY", MappingProxyType(changed))
    assert registry_hash() != original


@pytest.mark.parametrize("name,params", VARIANTS[:11])
def test_intraday_ignores_unfinished_candle(name, params):
    prices = five_minute_bars(2)
    strategy = REGISTRY[name]
    cutoff = prices.index[90]
    original = strategy.signals(prices, strategy.features(prices, params), params)
    changed = prices.copy()
    changed.loc[cutoff:, ["high", "low", "close", "volume"]] *= 2
    result = strategy.signals(changed, strategy.features(changed, params), params)
    assert [s for s in result if s.time <= cutoff] == [s for s in original if s.time <= cutoff]


@pytest.mark.parametrize("direction", [-1, 1])
def test_first_hour_is_frozen_and_signals_strictly_after_1015(direction):
    prices = five_minute_bars(1)
    prices.loc[:, ["open", "close"]] = 100.0
    prices.iloc[11, prices.columns.get_loc("close")] = 100 + 2 * direction
    # The 10:15 candle reverses violently, but is outside the first hour.
    prices.iloc[12:, prices.columns.get_loc("close")] = 100 - 10 * direction
    strategy, params = REGISTRY["first_hour_momentum"], {"threshold": 1.0}
    signals = strategy.signals(prices, strategy.features(prices, params), params)
    assert [(s.time.strftime("%H:%M"), s.target) for s in signals] == [("10:20", direction)]


@pytest.mark.parametrize("mode,direction", [("fade", -1), ("continue", 1)])
def test_gap_uses_first_open_and_previous_session_close(mode, direction):
    prices = five_minute_bars(2)
    prices.loc[:, ["open", "high", "low", "close"]] = 100.0
    prices.iloc[75:, prices.columns.get_loc("open")] = 103.0
    prices.iloc[75:, prices.columns.get_loc("close")] = 50.0
    strategy, params = REGISTRY["gap_play"], {"gap": 2, "mode": mode}
    signals = strategy.signals(prices, strategy.features(prices, params), params)
    assert [(s.time, s.target) for s in signals] == [(prices.index[75], direction)]


@pytest.mark.parametrize("name,params", VARIANTS)
def test_symbols_are_independent(name, params):
    prices = five_minute_bars(3, symbols=("ALPHA", "BETA"))
    strategy = REGISTRY[name]
    combined = strategy.features(prices, params)
    for symbol in ("ALPHA", "BETA"):
        single = prices[prices.symbol == symbol]
        pd.testing.assert_frame_equal(combined[combined.symbol == symbol], strategy.features(single, params))


def test_hash_includes_signal_source(monkeypatch):
    original = registry_hash()

    def different_signals(prices, features, params):
        return []

    changed = dict(REGISTRY)
    changed["orb"] = replace(changed["orb"], signals=different_signals)
    monkeypatch.setattr(strategies, "REGISTRY", MappingProxyType(changed))
    assert registry_hash() != original


def daily_bars(closes):
    closes = np.array(closes, dtype=float)
    return pd.DataFrame({
        "symbol": "ALPHA", "open": closes, "high": closes + .1,
        "low": closes - .1, "close": closes, "volume": 100,
    }, index=pd.bdate_range("2025-01-01", periods=len(closes), tz="Asia/Kolkata"))


def test_nday_breakout_uses_prior_n_sessions_and_exits_on_low():
    prices = daily_bars([100] * 20 + [102, 103, 98, 100])
    strategy, params = REGISTRY["nday_breakout"], {"n": 20}
    signals = strategy.signals(prices, strategy.features(prices, params), params)
    assert [(s.time, s.target) for s in signals] == [(prices.index[21], 1), (prices.index[23], 0)]


def test_breakout_exits_after_twenty_sessions():
    prices = daily_bars([100] * 20 + list(range(102, 126)))
    strategy, params = REGISTRY["nday_breakout"], {"n": 20}
    signals = strategy.signals(prices, strategy.features(prices, params), params)
    assert [(s.time, s.target) for s in signals[:2]] == [(prices.index[21], 1), (prices.index[41], 0)]


def test_trend_pullback_requires_rising_ma_and_exits_on_recovery():
    prices = daily_bars(list(np.linspace(80, 110, 55)) + [106, 111, 112])
    strategy, params = REGISTRY["trend_pullback"], {"ma": 50, "pullback": 3}
    signals = strategy.signals(prices, strategy.features(prices, params), params)
    assert [(s.time, s.target) for s in signals] == [(prices.index[56], 1), (prices.index[57], 0)]
    falling = daily_bars(list(np.linspace(120, 100, 60)))
    assert strategy.signals(falling, strategy.features(falling, params), params) == []


def test_short_reversal_is_long_only_and_exits_on_recovery():
    prices = daily_bars([100, 99, 98, 97, 96, 101, 102])
    strategy, params = REGISTRY["short_reversal"], {"lookback": 3}
    signals = strategy.signals(prices, strategy.features(prices, params), params)
    assert [(s.time, s.target) for s in signals] == [(prices.index[4], 1), (prices.index[6], 0)]


def test_swing_windows_count_sessions_on_five_minute_bars():
    prices = five_minute_bars(25)
    prices.loc[:, ["open", "close"]] = 100.0
    prices.loc[:, "high"] = 101.0
    prices.loc[:, "low"] = 99.0
    prices.iloc[20 * 75:21 * 75, prices.columns.get_loc("close")] = 102.0
    strategy, params = REGISTRY["nday_breakout"], {"n": 20}
    signals = strategy.signals(prices, strategy.features(prices, params), params)
    assert signals[0].time == prices.index[21 * 75]
    assert signals[0].target == 1


@pytest.mark.parametrize("direction", [-1, 1])
def test_vwap_reversion_enters_outside_band_exits_at_vwap(direction):
    prices = five_minute_bars(1).iloc[:8].copy()
    values = [100, 100, 100, 100, 100 + 10 * direction, 100 - 2 * direction, 100, 100]
    for column in ("open", "high", "low", "close"):
        prices[column] = values
    prices["volume"] = 100
    strategy, params = REGISTRY["vwap_revert"], {"deviation": 1.5}
    signals = strategy.signals(prices, strategy.features(prices, params), params)
    assert [(s.time, s.target) for s in signals[:2]] == [
        (prices.index[5], -direction), (prices.index[6], 0),
    ]


@pytest.mark.parametrize("name,params", VARIANTS[11:])
def test_swing_lookahead_after_full_warmup(name, params):
    prices = daily_bars(np.linspace(80, 160, 125) + 6 * np.sin(np.arange(125)))
    strategy = REGISTRY[name]
    assert check_lookahead(lambda frame: strategy.features(frame, params), prices).verdict == "PASS"
    full = strategy.signals(prices, strategy.features(prices, params), params)
    assert any(signal.target == 1 for signal in full)
    for cutoff in prices.index[100::5]:
        prefix = prices.loc[:cutoff]
        assert strategy.signals(prefix, strategy.features(prefix, params), params) == [
            signal for signal in full if signal.time <= cutoff
        ]


@pytest.mark.parametrize("threshold", [.5, 1.0])
@pytest.mark.parametrize("direction", [-1, 1])
def test_momentum_includes_exact_threshold(threshold, direction):
    prices = five_minute_bars(1)
    prices["open"] = 100.0
    prices["close"] = 100.0 + threshold * direction
    strategy, params = REGISTRY["first_hour_momentum"], {"threshold": threshold}
    signals = strategy.signals(prices, strategy.features(prices, params), params)
    assert len(signals) == 1
    assert signals[0].target == direction
