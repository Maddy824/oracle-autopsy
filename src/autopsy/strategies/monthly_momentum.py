"""Frozen 12-1 momentum and volatility-scaled momentum, Amendments 1 and 1a."""

import json

import numpy as np
import pandas as pd

from autopsy.checks import CheckResult
from autopsy.engine import Rebalance
from autopsy.strategies.earnings_reaction import _index
from autopsy.strategies.intraday import _check_features
from autopsy.strategies.weekly_loser_reversal import data_check as daily_data_check

VARIANTS = ("M12", "M12V")
BIAS = ("Candidates come from Kite's 2026-11-05 instrument list. Companies delisted or merged "
        "before that date are absent; this residual survivorship bias is not measurable as missing member-months.")
FUND_NAME = r"\bETF\b|BEES|\bINAV\b|\bNAV$|AMC\s*-|\bFUND\b|\bREIT\b|\bINVIT\b|BHARAT BOND"
FUND_SYMBOL = r"BEES$|IETF$|ETF$|INAV$"


def candidate_symbols(instruments):
    """Amendment 1a, applied to the owner's frozen 2026-11-05 Kite CSV."""
    required = {"segment", "instrument_type", "tradingsymbol", "name"}
    if not required <= set(instruments):
        raise ValueError("Kite instrument table needs segment, instrument_type, tradingsymbol and name")
    valid = (instruments.segment.eq("NSE") & instruments.instrument_type.eq("EQ")
             & ~instruments.tradingsymbol.str.contains("-", regex=False, na=True)
             & ~instruments.name.str.contains(FUND_NAME, case=False, regex=True, na=True)
             & ~instruments.tradingsymbol.str.contains(FUND_SYMBOL, case=False, regex=True, na=True))
    return tuple(sorted(set("NSE:" + symbol for symbol in instruments.loc[valid, "tradingsymbol"])))


def attach_candidates(prices, instruments):
    result = prices.copy()
    result.attrs["monthly_candidates"] = json.dumps(candidate_symbols(instruments))
    return result


def data_check(prices):
    check = daily_data_check(prices)
    reason = check.evidence.get("reason")
    if reason:
        reason = reason.replace("weekly_loser_reversal", "monthly_momentum")
    return CheckResult("monthly_momentum_data", "CAN'T TELL" if reason else "PASS",
                       {"reason": reason} if reason else {"survivorship_bias": BIAS})


def with_warmup(prices, history):
    """Freeze only the 252 index sessions strictly preceding this window.

    Stored as JSON so pandas copies do not repeatedly duplicate a large object.
    The research lock hashes this context along with the window's actual bars.
    """
    result = prices.copy()
    if result.empty:
        return result
    days = _index(history).index
    prior = days[days < result.index.min().normalize()][-252:]
    warmup = history.loc[history.index.normalize().isin(prior)]
    columns = ["symbol", "open", "high", "low", "close", "volume"]
    result.attrs["monthly_warmup"] = json.dumps({"columns": columns,
        "index": [time.isoformat() for time in warmup.index],
        "data": warmup[columns].to_numpy().tolist()}, separators=(",", ":"))
    return result


def _history(prices):
    if not prices.attrs.get("monthly_warmup") or prices.empty:
        return prices
    payload = json.loads(prices.attrs["monthly_warmup"])
    warmup = pd.DataFrame(payload["data"], columns=payload["columns"],
                          index=pd.to_datetime(payload["index"], utc=True).tz_convert("Asia/Kolkata"))
    warmup = warmup.loc[warmup.index < prices.index.min()]
    result = pd.concat([warmup, prices]).sort_index(kind="stable")
    result.attrs = prices.attrs.copy()
    return result


def features(prices, params):
    if params["variant"] not in VARIANTS:
        raise ValueError("unknown monthly momentum variant")
    history = _history(prices)
    days = _index(history).index
    symbols = pd.Index(sorted(history.symbol.unique()))
    # Dense session-by-symbol arrays make missing scheduled sessions explicit.
    keys = pd.MultiIndex.from_arrays([history.index.normalize(), history.symbol])
    close = pd.Series(history.close.to_numpy(), index=keys).unstack().reindex(index=days, columns=symbols)
    values = history[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    valid = np.isfinite(values).all(axis=1) & (values > 0).all(axis=1)
    valid = pd.Series(valid, index=keys).unstack().reindex(index=days, columns=symbols, fill_value=False).fillna(False)
    eligible = valid.astype(float).rolling(253, min_periods=253).sum().eq(253)
    eligible.loc[:, symbols == prices.attrs.get("index_symbol")] = False
    # Bare OHLCV inputs may already be candidate-filtered (including synthetic
    # fixtures). Attached frozen instruments additionally enforce name/type rules.
    candidates = prices.attrs.get("monthly_candidates")
    if candidates is not None:
        eligible.loc[:, ~symbols.isin(json.loads(candidates))] = False
    else:
        eligible.loc[:, symbols.str.contains("-", regex=False) | symbols.str.contains(FUND_SYMBOL, case=False)] = False
    traded = pd.Series((history.close * history.volume).to_numpy(), index=keys).unstack().reindex(index=days, columns=symbols)
    median = traded.rolling(126, min_periods=126).median()
    universe = median.where(eligible).rank(axis=1, ascending=False, method="first").le(100)
    momentum = close.shift(21) / close.shift(252) - 1
    volatility = np.log(close.where(close > 0)).diff().rolling(252, min_periods=252).std(ddof=1)
    score = momentum if params["variant"] == "M12" else momentum / volatility
    rank = score.where(universe).rank(axis=1, ascending=False, method="first")
    row = days.get_indexer(prices.index.normalize())
    col = symbols.get_indexer(prices.symbol)
    result = pd.DataFrame({"symbol": prices.symbol.to_numpy()}, index=prices.index)
    for name, frame in (("history_eligible", eligible), ("median_traded_value", median),
                        ("universe", universe), ("m12", momentum), ("volatility", volatility),
                        ("score", score), ("rank", rank)):
        # Invalid index context is reported by data_check; never wrap -1 to a future row.
        values = frame.to_numpy()[np.maximum(row, 0), col] if len(days) else np.full(len(row), np.nan)
        result[name] = np.where(row >= 0, values, False if name in ("history_eligible", "universe") else np.nan)
    return result


def rebalance_days(prices):
    days = _index(prices).index
    months = days.year * 12 + days.month
    return days[:-1][months[:-1] != months[1:]]


def signals(prices, features, params):
    _check_features(prices, features)
    days = rebalance_days(prices)
    result = []
    rows = features.loc[features.index.normalize().isin(days)]
    for _, rows in rows.groupby(rows.index.normalize(), sort=True):
        pool = tuple(sorted(rows.loc[rows.universe.astype(bool), "symbol"]))
        target = tuple(rows.loc[rows["rank"].le(5)].sort_values(["rank", "symbol"]).symbol)
        result.append(Rebalance(rows.index.max(), target, pool))
    return result


def benchmark(prices, start, end, capital=200_000):
    """Index buy-and-hold, without ETF fees or a GO gate."""
    index = _index(prices)
    index = index.loc[(index.index >= start) & (index.index < end)]
    if index.empty:
        return None
    from autopsy.stats import sharpe
    returns = index.pct_change().fillna(0)
    opening = index.iloc[0]
    basis = "Nifty 50 index close-to-close buy-and-hold; before costs"
    if prices.attrs.get("monthly_index_opens"):
        opens = {pd.Timestamp(time).normalize(): value for time, value in json.loads(prices.attrs["monthly_index_opens"])}
        if index.index[0] in opens:
            opening = opens[index.index[0]]
            returns.iloc[0] = index.iloc[0] / opening - 1
            basis = "Nifty 50 index first-open to final-close buy-and-hold; before costs"
    return {"net_profit": float(capital * (index.iloc[-1] / opening - 1)),
            "sharpe": sharpe(returns), "basis": basis}
