"""Task 7 statistics, with independent scalar pricing of the random baseline."""

from dataclasses import replace
from math import sqrt

import numpy as np
import pandas as pd
import pytest

from autopsy.costs import load_rates, trade_costs
from autopsy.engine import Signal, run_backtest
from autopsy.stats import (
    MinTradesError, bootstrap_lower, daily_net_pnl, deflated_sharpe,
    max_drawdown, random_entry_baseline, sharpe,
)


def baseline_fixture(mode="intraday", count=36, flat=False):
    days = pd.bdate_range("2025-01-01", periods=count * (3 if mode == "swing" else 1),
                          tz="Asia/Kolkata")
    frames, signals = [], []
    for i, day in enumerate(days):
        # Include short sessions and evening special sessions, plus bars after
        # the regular cutoff which must never be sampled as intraday entries.
        clock = ["09:15"] if mode == "swing" else (
            ["18:00", "18:05", "18:10", "18:15", "18:20", "18:25"] if i % 7 == 0
            else ["09:15", "09:20", "09:25", "09:30", "09:35"] if i % 7 == 1
            else ["09:15", "09:20", "09:25", "09:30", "09:35", "15:10", "15:15", "15:20"]
        )
        times = pd.DatetimeIndex([day + pd.Timedelta(t + ":00") for t in clock])
        for j, symbol in enumerate(("ALPHA", "BETA")):
            values = np.full(len(times), 100.0 + 100 * j)
            if not flat:
                values += i * .13 + np.arange(len(times)) ** 2 * .17
            frames.append(pd.DataFrame(dict(symbol=symbol, open=values, high=values + 1,
                                            low=values - 1, close=values + .1, volume=100),
                                       index=times))
        if mode == "intraday":
            symbol = ("ALPHA", "BETA")[i % 2]
            signals.extend([Signal(times[0], symbol, 1 if i % 3 else -1),
                            Signal(times[3], symbol, 0)])
        elif i % 3 in (0, 1):
            signals.append(Signal(times[0], ("ALPHA", "BETA")[(i // 3) % 2],
                                  1 if i % 3 == 0 else 0))
    prices = pd.concat(frames).sort_index(kind="stable")
    # A custom snapshot catches accidentally falling back to default rates.
    original = load_rates("zerodha")
    values = {k: dict(v) for k, v in original.segment_rates.items()}
    values["intraday_equity"]["brokerage_cap"] = 7.0
    values["delivery_equity"]["dp_sell"] = 23.0
    rates = replace(original, segment_rates=values)
    return run_backtest(prices, signals, mode, slippage_bps=25, rates=rates), rates


def scalar_baseline(record, rates, mode, runs, seed):
    """Enumerate legal pairs and reprice every sampled order with trade_costs."""
    rng = np.random.default_rng(seed)
    result = np.zeros(runs)
    sold = [set() for _ in range(runs)]
    for entry, exit in zip(record.fills[::2], record.fills[1::2]):
        bars = record.prices[record.prices.symbol == entry.symbol]
        candidates = []
        if mode == "intraday":
            duration = exit.time - entry.time
            for day, session in bars.groupby(bars.index.normalize()):
                deadline = day + pd.Timedelta(hours=15, minutes=15)
                after = session.index[session.index >= deadline]
                cutoff = after[0] if session.index[0] <= deadline and len(after) else session.index[-1]
                for time in session.index[1:]:
                    end = time + duration
                    if time < cutoff and end <= cutoff and end in session.index:
                        candidates.append((time, end))
        else:
            duration = bars.index.get_loc(exit.time) - bars.index.get_loc(entry.time)
            candidates = [(bars.index[i], bars.index[i + duration])
                          for i in range(1, len(bars) - duration)]
        chosen = rng.integers(len(candidates), size=runs)
        for run, index in enumerate(chosen):
            start, end = candidates[index]
            for fill, time in ((entry, start), (exit, end)):
                direction = 1 if fill.side == "BUY" else -1
                notional = fill.qty * float(bars.loc[time, "open"]) * (1 + direction * .0025)
                key = (fill.symbol, time.normalize())
                fee = trade_costs(fill.side, notional,
                                  "intraday_equity" if mode == "intraday" else "delivery_equity",
                                  rates, symbol_sold_today=key in sold[run]).total
                result[run] -= direction * notional + fee
                if fill.side == "SELL":
                    sold[run].add(key)
    return result


def test_drawdown_includes_start():
    assert max_drawdown([100, 90, 80]) == pytest.approx(-.2)
    assert max_drawdown([100, 110, 105, 120]) == pytest.approx(105 / 110 - 1)
    assert max_drawdown([]) == 0
    assert sharpe([0, 0, 0]) == 0
    assert sharpe([.01, -.01, .02]) == pytest.approx(
        np.mean([.01, -.01, .02]) / np.std([.01, -.01, .02], ddof=1) * sqrt(252))
    record, _ = baseline_fixture()
    expected = record.reported_equity.groupby(record.reported_equity.index.normalize()).last()
    expected = expected.diff().fillna(expected.iloc[0] - record.start_cash)
    pd.testing.assert_series_equal(daily_net_pnl(record), expected.rename("net_pnl"))
    assert daily_net_pnl(record).sum() == pytest.approx(record.reported_equity.iloc[-1] - record.start_cash)


def test_bootstrap_zero_mean_not_positive():
    values = np.random.default_rng(0).normal(size=500)
    assert bootstrap_lower(values) < 0
    assert bootstrap_lower(values, n=200, seed=7) == bootstrap_lower(values, n=200, seed=7)
    # Long blocks retain dependence; IID resampling would miss this widening.
    persistent = np.repeat([-1., 1.], 250)
    assert bootstrap_lower(persistent, block=50) < bootstrap_lower(persistent, block=1) - .2


def test_bootstrap_strong_mean_positive():
    assert bootstrap_lower(np.random.default_rng(0).normal(1, 1, 500)) > 0
    assert bootstrap_lower([2., 2., 2.]) == 2
    with pytest.raises(ValueError):
        bootstrap_lower([])


@pytest.mark.parametrize("mode", ["intraday", "swing"])
@pytest.mark.parametrize("flat", [False, True])
def test_baseline_matches_trade_count(mode, flat):
    record, rates = baseline_fixture(mode=mode, flat=flat)
    assert len(record.fills) == 72
    actual = random_entry_baseline(record, record.prices, runs=100, seed=42)
    # Exactly 36 round trips per run, with the original symbol, side, shares,
    # holding duration, slippage and current notional-based fees. Dropping or
    # duplicating trades changes even the flat-market loss in this comparison.
    np.testing.assert_allclose(actual, scalar_baseline(record, rates, mode, 100, 42), atol=1e-7)
    np.testing.assert_array_equal(actual, random_entry_baseline(record, record.prices, 100, 42))
    if not flat:
        assert not np.array_equal(actual, random_entry_baseline(record, record.prices, 100, 43))


def test_dsr_reference_value():
    """Hand-worked Bailey/Lopez de Prado (2014), equations (1) and (2).

    https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
    SR=1 annualised, N=10, T=250, skew=0, Pearson kurtosis=3.
    The signature omits across-trial variance; assume the zero-Sharpe null
    variance 1/(T-1), with independent trials (a reported heuristic).
    Daily s=1/sqrt(252)=0.06299407883; gamma=0.57721566490.
    Phi^-1(.9)=1.28155156554; Phi^-1(1-1/(10e))=1.78924176458.
    Expected max standard normal=(1-gamma)*1.28155156554
      + gamma*1.78924176458=1.57459830135.
    SR0=1.57459830135/sqrt(249)=0.09978611284.
    z=(s-SR0)*sqrt(249)/sqrt(1 + s*s/2)=-0.57999339881.
    DSR=Phi(z)=0.28095953469. Values are fixed, not generated by the SUT.
    """
    assert deflated_sharpe(1., 10, 250, 0., 3.) == pytest.approx(.28095953469, abs=1e-3)
    assert deflated_sharpe(1., 1, 250, 0., 3.) == pytest.approx(.8396609467, abs=1e-3)
    assert deflated_sharpe(1., 100, 250, 0., 3.) < deflated_sharpe(1., 10, 250, 0., 3.)
    assert deflated_sharpe(1., 10, 250, -1., 5.) != deflated_sharpe(1., 10, 250, 0., 3.)


@pytest.mark.parametrize("count", [0, 1, 29])
def test_zero_trades(count):
    record, _ = baseline_fixture()
    record.fills = record.fills[:2 * count]
    for function in (lambda: daily_net_pnl(record),
                     lambda: random_entry_baseline(record, record.prices)):
        with pytest.raises(MinTradesError, match="30"):
            function()
