"""Offline, invented workload. Run with .venv/bin/python tests/benchmark_random_portfolio.py."""

import json
from time import perf_counter

import numpy as np
import pandas as pd

from autopsy.costs import load_rates
from autopsy.engine import run_backtest
from autopsy.news.events import with_events
from autopsy.stats import _EarningsPortfolio
from test_earnings_reaction import INDEX, notice
from autopsy.strategies import earnings_reaction as reaction


def workload(symbols=100, sessions=2700):
    times = pd.bdate_range("2015-01-01", periods=sessions, tz="Asia/Kolkata")
    rng = np.random.default_rng(28)
    frames, events = [], []
    for i in range(symbols):
        symbol = f"STOCK{i:03}"
        returns = rng.normal(.0002, .015, sessions)
        event_days = np.arange(205 + i % 20, sessions - 12, 63)
        returns[event_days] = .04
        close = 100 * np.exp(returns.cumsum())
        opens = np.r_[100, close[:-1]] * np.exp(rng.normal(0, .002, sessions))
        frames.append(pd.DataFrame({"symbol": symbol, "open": opens, "close": close,
                                    "high": np.maximum(opens, close) * 1.01,
                                    "low": np.minimum(opens, close) * .99,
                                    "volume": 10000}, index=times))
        events.extend(notice(symbol, times[d] - pd.Timedelta(hours=7)) for d in event_days)
    prices = with_events(pd.concat(frames).sort_index(kind="stable"), events)
    prices.attrs.update(bar_interval="D", index_symbol=INDEX,
                        index_prices=json.dumps([[t.isoformat(), 100 + i * .01]
                                                 for i, t in enumerate(times)]))
    return prices


if __name__ == "__main__":
    prices = workload()
    params = {"variant": "h10_regime"}
    start = perf_counter()
    features = reaction.features(prices, params)
    signals = reaction.signals(prices, features, params)
    print(f"features/signals: {perf_counter() - start:.3f}s; orders={len(signals)}", flush=True)
    start = perf_counter()
    record = run_backtest(prices, signals, "swing", slippage_bps=20, rates=load_rates("zerodha"))
    elapsed = perf_counter() - start
    print(f"engine: {elapsed:.3f}s; 1000 projection={elapsed * 1000:.1f}s; fills={len(record.fills)}", flush=True)
    start = perf_counter()
    portfolio = _EarningsPortfolio(record, params)
    print(f"baseline preparation/replay: {perf_counter() - start:.3f}s", flush=True)
    rng = np.random.default_rng(0)
    start = perf_counter()
    portfolio.run(portfolio.draw(rng))
    elapsed = perf_counter() - start
    print(f"prepared random engine: {elapsed:.3f}s; 1000 projection={elapsed * 1000:.1f}s", flush=True)
    start = perf_counter()
    for _ in range(1000):
        portfolio.run(portfolio.draw(rng))
    print(f"1000 sequential random runs: {perf_counter() - start:.3f}s; processes=1", flush=True)
