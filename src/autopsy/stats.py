"""Descriptive statistics and seeded, CPU-only research baselines."""

from math import ceil, e, isclose, isfinite, sqrt
from numbers import Integral
from statistics import NormalDist

import numpy as np
import pandas as pd

from autopsy.calendar import _intraday_closes
from autopsy.costs import RateTable, trade_costs
from autopsy.engine import Signal, _prepare_prices, _run_prepared
from autopsy.types import RunRecord, _validated_prices


class MinTradesError(ValueError):
    """Fewer than 30 completed trades: the caller must report CAN'T TELL."""


def _round_trips(record):
    """Pair whole-position fills per symbol, including same-bar reversals.

    Unclosed positions have no observed holding duration and do not count as
    completed trades. Partial closes/scaling are not produced by the engine.
    """
    pending, trades = {}, []
    for fill in sorted(record.fills, key=lambda fill: fill.time):
        entry = pending.pop(fill.symbol, None)
        if entry is None:
            pending[fill.symbol] = fill
        else:
            factor = 1.
            if "share_multiplier" in record.prices:
                between = record.prices[(record.prices.symbol == fill.symbol)
                                        & (record.prices.index > entry.time)
                                        & (record.prices.index <= fill.time)]
                factor = float(between.share_multiplier.prod())
            if (entry.side == fill.side or entry.time >= fill.time
                    or not isclose(entry.qty * factor, fill.qty, rel_tol=0, abs_tol=1e-9)):
                raise ValueError("fills must describe whole-position round trips")
            trades.append((entry, fill))
    if len(trades) < 30:
        raise MinTradesError(f"at least 30 completed trades required; got {len(trades)}")
    return trades


def _values(values, name):
    result = np.asarray(values, dtype=float)
    if result.ndim != 1 or not np.isfinite(result).all():
        raise ValueError(f"{name} must be a finite one-dimensional sequence")
    return result


def _positive_integer(value, name):
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def daily_net_pnl(record: RunRecord) -> pd.Series:
    """Observed-session equity changes, after costs and before income tax.

    Include the first session's change from start_cash and zero-PnL observed
    sessions; do not invent weekend/holiday observations. Open positions stay
    marked to market. Require 30 completed trades for inferential consumers.
    """
    _round_trips(record)
    equity = record.reported_equity.sort_index()
    _values(equity, "reported_equity")
    if equity.empty or not equity.index.is_unique:
        raise ValueError("reported_equity must contain unique observations")
    daily = equity.groupby(equity.index.normalize()).last()
    pnl = daily.diff()
    pnl.iloc[0] = daily.iloc[0] - record.start_cash
    pnl.attrs = {}
    return pnl.rename("net_pnl")


def max_drawdown(equity) -> float:
    """Worst fractional decline (nonpositive), including the first value.

    Pass initial capital as the first observation when the curve starts after
    a fill. An empty curve has no drawdown; its first capital must be positive.
    Negative later equity can legitimately produce a drawdown below -1.
    """
    values = _values(equity, "equity")
    if not len(values):
        return 0.0
    if values[0] <= 0:
        raise ValueError("starting equity must be positive")
    return float(np.min(values / np.maximum.accumulate(values) - 1))


def sharpe(daily_returns) -> float:
    """Daily mean / sample standard deviation, annualised by sqrt(252).

    Fewer than two observations or zero variance returns 0, not spurious
    infinite evidence. Returns are on the full account, with risk-free rate 0.
    """
    values = _values(daily_returns, "daily_returns")
    if len(values) < 2:
        return 0.0
    deviation = float(values.std(ddof=1))
    return float(values.mean() / deviation * sqrt(252)) if deviation else 0.0


def bootstrap_lower(daily_pnl, alpha=0.05, n=5000, block: int | None = None, seed=0) -> float:
    """One-sided percentile bound using the circular stationary bootstrap.

    Start uniformly; at each observation restart uniformly with probability
    1/block, otherwise advance one day (wrapping at the end). Thus blocks have
    geometric lengths with the specified mean. Memory use is O(n), not O(n*T).
    """
    values = _values(daily_pnl, "daily_pnl")
    if not len(values):
        raise ValueError("daily_pnl must not be empty")
    _positive_integer(n, "n")
    if not isfinite(alpha) or not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    block = ceil(len(values) ** (1 / 3)) if block is None else block
    _positive_integer(block, "block")
    rng = np.random.default_rng(seed)
    index = rng.integers(len(values), size=n)
    totals = values[index].copy()
    for _ in range(1, len(values)):
        index = np.where(rng.random(n) < 1 / block,
                         rng.integers(len(values), size=n), (index + 1) % len(values))
        totals += values[index]
    return float(np.quantile(totals / len(values), alpha))


def _cost_curve(side, segment, rates):
    """Derive the exact piecewise-linear fee curve from scalar trade_costs.

    Only brokerage has a kink (its cap). DP is handled once per sampled
    symbol/day below. This avoids hundreds of thousands of Decimal calls
    while retaining trade_costs as the pricing authority.
    """
    fields = rates.segment_rates[segment]
    rate, cap = fields["brokerage_rate"], fields["brokerage_cap"]

    def fee(notional):
        return trade_costs(side, float(notional), segment, rates, symbol_sold_today=True).total

    if not rate or not cap:
        return float("inf"), fee(1), 0.0
    threshold = cap / rate
    at_cap = fee(threshold)
    return threshold, at_cap / threshold, (fee(2 * threshold) - at_cap) / threshold


def random_entry_baseline(record, prices, runs=1000, seed=0, *, eligible_signal_days=None) -> np.ndarray:
    """Net PnL of independent random round trips, conditional on actual trades.

    Preserve each completed trade's symbol, side and entry whole-share quantity.
    Exit quantities follow corporate actions in the sampled holding interval.
    Intraday holds retain exact elapsed time and stay inside the engine's
    observed-session cutoff (including short/evening sessions). Swing holds
    retain the number of observed symbol bars, so weekends do not lengthen a
    trading-day horizon. Require a preceding bar for next-bar entries; for
    intraday it must be in the same session. Price both legs at sampled opens.

    run_backtest stores mode, slippage and the exact rate snapshot in
    reported_equity.attrs['autopsy_execution']; manually assembled records
    must supply the same metadata. Missing settings are never guessed.

    This is a conditional entry-timing benchmark: sample trades independently
    with replacement, allowing overlaps, without portfolio resizing or cash
    rejection (which would change the required trade count). Unclosed trades
    are excluded. Vectorise runs and cache eligible entry/exit pairs.

    eligible_signal_days optionally restricts the preceding bar's session to
    earnings-reaction days (some tradable symbol had a timed results event).
    This matches season timing, not portfolio capacity or cash constraints.
    """
    trades = _round_trips(record)
    _positive_integer(runs, "runs")
    config = record.reported_equity.attrs.get("autopsy_execution")
    if not isinstance(config, dict) or not {"mode", "slippage_bps", "rates"} <= config.keys():
        raise ValueError("record needs autopsy_execution metadata from run_backtest")
    mode, slippage = config["mode"], config["slippage_bps"]
    if mode not in ("intraday", "swing") or not isfinite(slippage) or not 0 <= slippage < 10_000:
        raise ValueError("invalid execution mode or slippage")
    rates = RateTable(**config["rates"])
    segment = "intraday_equity" if mode == "intraday" else "delivery_equity"
    prices = _validated_prices(prices).sort_index(kind="stable")
    if not np.isfinite(prices.open).all() or (prices.open <= 0).any():
        raise ValueError("open prices must be finite and positive")
    groups = {symbol: bars for symbol, bars in prices.groupby("symbol", sort=False)}
    source = {symbol: bars.sort_index() for symbol, bars in record.prices.groupby("symbol")}
    cutoffs = _intraday_closes(prices) if mode == "intraday" else {}
    curves = {side: _cost_curve(side, segment, rates) for side in ("BUY", "SELL")}
    dp = (trade_costs("SELL", 1., segment, rates).total
          - trade_costs("SELL", 1., segment, rates, symbol_sold_today=True).total)
    rng = np.random.default_rng(seed)
    eligible_days = (None if eligible_signal_days is None else
                     pd.DatetimeIndex(list(eligible_signal_days)).normalize())
    result = np.zeros(runs)
    pools, bar_data, sold_days, share_factors = {}, {}, {}, {}
    row = np.arange(runs)
    for entry, exit in trades:
        symbol = entry.symbol
        if symbol not in groups or symbol not in source:
            raise ValueError(f"missing prices for {symbol}")
        if mode == "swing" and entry.side != "BUY":
            raise ValueError("swing trades must be long only")
        original = source[symbol].index
        locations = original.get_indexer([entry.time, exit.time])
        if (locations < 0).any():
            raise ValueError("trade endpoints must be in record.prices")
        duration = exit.time - entry.time if mode == "intraday" else int(locations[1] - locations[0])
        key = (symbol, duration)
        bars = groups[symbol]
        times = bars.index
        if symbol not in bar_data:
            days = times.normalize()
            day_codes, unique_days = pd.factorize(days)
            deadlines = (pd.DatetimeIndex([cutoffs[symbol, day] for day in days])
                         if mode == "intraday" else None)
            bar_data[symbol] = (days, day_codes, deadlines, bars.open.to_numpy(dtype=float))
            factors = (bars.share_multiplier.to_numpy(dtype=float) if "share_multiplier" in bars
                       else np.ones(len(bars)))
            if not np.isfinite(factors).all() or (factors <= 0).any():
                raise ValueError("invalid corporate action factors")
            share_factors[symbol] = factors.cumprod()
            if dp:
                sold_days[symbol] = np.zeros((runs, len(unique_days)), dtype=bool)
        days, day_codes, deadlines, opens = bar_data[symbol]
        if key not in pools:
            starts = np.arange(1, len(times))
            if mode == "intraday":
                ends = times.get_indexer(times[starts] + duration)
                valid = ((ends >= 0) & (days[starts] == days[starts - 1])
                         & (times[starts] < deadlines[starts])
                         & (times[starts] + duration <= deadlines[starts]))
            else:
                ends = starts + duration
                valid = ends < len(times)
            if eligible_days is not None:
                valid &= days[starts - 1].isin(eligible_days)
            starts, ends = starts[valid], ends[valid]
            if not len(starts):
                raise ValueError(f"no tradable entries for {symbol} with holding duration {duration}")
            pools[key] = (starts, ends)
        starts, ends = pools[key]
        choices = rng.integers(len(starts), size=runs)
        cumulative = share_factors[symbol]
        exit_qty = entry.qty * cumulative[ends[choices]] / cumulative[starts[choices]]
        if not np.isclose(exit_qty, np.rint(exit_qty), rtol=0, atol=1e-9).all():
            raise ValueError("sampled corporate action needs fractional-share cash-in-lieu data")
        for fill, indices in ((entry, starts[choices]), (exit, ends[choices])):
            direction = 1 if fill.side == "BUY" else -1
            qty = entry.qty if fill is entry else np.rint(exit_qty)
            turnover = qty * opens[indices] * (1 + direction * slippage / 10_000)
            cap, lower, upper = curves[fill.side]
            fee = np.minimum(turnover, cap) * lower + np.maximum(turnover - cap, 0) * upper
            if dp and fill.side == "SELL":
                seen = sold_days[symbol]
                fee += dp * ~seen[row, day_codes[indices]]
                seen[row, day_codes[indices]] = True
            result -= direction * turnover + fee
    return result


class _ManagedPortfolio:
    """Prepare once, then replace only symbol selection in managed orders.

    Counts mean submitted strategy orders, including capacity/cash rejections,
    not successful fills. Sampling is uniform without replacement per session;
    the draw order supplies random priority. Held symbols remain in the pool,
    just as strategy orders for already-held symbols remain engine inputs.
    Earnings pools require a completed bar and positive finite ATR20 that day;
    weekly losers use their history eligibility without the loser filter.
    No future bar, return, reaction or event on that symbol filters the pool.
    """

    def __init__(self, record, params, family="earnings_reaction"):
        from autopsy.strategies import earnings_reaction as reaction
        from autopsy.strategies import weekly_loser_reversal as reversal

        strategy = {"earnings_reaction": reaction, "weekly_loser_reversal": reversal}[family]

        config = record.reported_equity.attrs.get("autopsy_execution")
        if not isinstance(config, dict) or not {"mode", "slippage_bps", "rates"} <= config.keys():
            raise ValueError("record needs autopsy_execution metadata from run_backtest")
        if config["mode"] != "swing":
            raise ValueError(f"{'earnings' if strategy is reaction else family} portfolio requires swing execution")
        self.capital = record.start_cash
        self.slippage = config["slippage_bps"]
        self.rates = RateTable(**config["rates"])
        prices = record.prices.loc[record.prices.symbol != record.prices.attrs.get("index_symbol")]
        check = strategy.data_check(prices)
        if check.verdict != "PASS":
            raise ValueError(check.evidence["reason"])
        self.prepared = _prepare_prices(prices, "swing")
        features = strategy.features(prices, params)
        self.strategy_signals = strategy.signals(prices, features, params)
        self.hold = (reaction.VARIANTS[params["variant"]][0] if strategy is reaction
                     else reversal.VARIANTS[params["variant"]])
        season = {day for _, day in reaction.event_sessions(prices)} if strategy is reaction else None
        counts = {}
        for signal in self.strategy_signals:
            if season is not None and signal.time.normalize() not in season:
                raise ValueError("strategy order outside eligible event season")
            counts[signal.time] = counts.get(signal.time, 0) + 1
        self.pools = []
        valid = features.loc[np.isfinite(features.atr20) & (features.atr20 > 0)]
        if strategy is reversal:
            valid = valid.loc[valid.history_eligible]
        for time, bars in valid.groupby(level=0, sort=True):
            count = counts.get(time, 0)
            if not count:
                continue
            bars = bars.sort_values("symbol")
            pool = tuple(zip(bars.symbol, 2 * bars.atr20))
            if count > len(pool):
                raise ValueError("insufficient tradable symbols for strategy order count")
            self.pools.append((time, count, pool))

        # The locked record must actually be this strategy/configuration. This
        # also guards against accidentally using fill counts or a different
        # warm-up window when constructing the random comparison.
        fills, equity = self.run(self.strategy_signals)
        if fills != record.fills or not equity.equals(record.reported_equity):
            raise ValueError(f"{'earnings' if strategy is reaction else family} portfolio replay does not match strategy record")

    def draw(self, rng):
        signals = []
        for time, count, pool in self.pools:
            for priority, index in enumerate(rng.choice(len(pool), size=count, replace=False)):
                symbol, distance = pool[index]
                signals.append(Signal(time, symbol, 1, priority=-float(priority),
                                      risk_distance=float(distance), holding_sessions=self.hold))
        return signals

    def run(self, signals):
        return _run_prepared(self.prepared, signals, "swing", self.capital,
                             slippage_bps=self.slippage, rates=self.rates)


class _EarningsPortfolio(_ManagedPortfolio):
    """Compatibility name for the unchanged earnings-family sampler."""


def random_portfolio_baseline(record, params, runs=1000, seed=0, *, family="earnings_reaction") -> np.ndarray:
    """Managed-family full-engine null: final marked equity minus start cash.

    Reuse completed ATR and validated market inputs; each seeded run has fresh
    portfolio state and the exact strategy engine, costs and recorded slippage.
    Unlike the legacy sampler, open holdings contribute and random portfolios
    need not complete 30 trades. The verdict checks the strategy's trade count.
    """
    _positive_integer(runs, "runs")
    portfolio = _ManagedPortfolio(record, params, family)
    rng = np.random.default_rng(seed)
    result = np.empty(runs)
    for i in range(runs):
        _, equity = portfolio.run(portfolio.draw(rng))
        result[i] = float(equity.iloc[-1]) - record.start_cash
    return _values(result, "random portfolio profits")


def deflated_sharpe(sr, n_trials, n_obs, skew, kurt) -> float:
    """Bailey & Lopez de Prado (2014), equations (1)-(2), as a heuristic.

    sr is annualised (sqrt(252)); n_obs counts daily observations; kurt is
    Pearson kurtosis (Normal=3), not excess kurtosis. The prescribed signature
    lacks across-trial SR variance, so assume independent trials with daily
    zero-Sharpe null variance 1/(n_obs-1). This approximation cannot capture
    empirical between-strategy dispersion or correlated trials.

    SR0 = [(1-gamma)*Phi^-1(1-1/N) + gamma*Phi^-1(1-1/(N*e))]
          / sqrt(T-1), with Euler-Mascheroni gamma (not Euler's number e).
    DSR = Phi((s-SR0)*sqrt(T-1)/sqrt(1-skew*s+(kurt-1)*s*s/4)).
    One trial has SR0=0. Source: https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
    """
    _positive_integer(n_trials, "n_trials")
    _positive_integer(n_obs, "n_obs")
    if n_obs < 2 or not all(isfinite(value) for value in (sr, skew, kurt)):
        raise ValueError("finite moments and at least two observations required")
    if kurt < skew * skew + 1:
        raise ValueError("Pearson kurtosis must be at least skew**2 + 1")
    daily_sr = sr / sqrt(252)
    variance = 1 - skew * daily_sr + (kurt - 1) * daily_sr ** 2 / 4
    if variance <= 0:
        raise ValueError("Sharpe variance must be positive")
    normal = NormalDist()
    gamma = 0.5772156649015329
    # Symmetry avoids cancellation in 1-p for large numbers of trials.
    expected_max = (-(1 - gamma) * normal.inv_cdf(1 / n_trials)
                    - gamma * normal.inv_cdf(1 / (n_trials * e))) if n_trials > 1 else 0.0
    benchmark = expected_max / sqrt(n_obs - 1)
    return float(normal.cdf((daily_sr - benchmark) * sqrt(n_obs - 1) / sqrt(variance)))
