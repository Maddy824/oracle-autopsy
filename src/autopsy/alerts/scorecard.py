"""Evening scorecard: paper trades after Indian costs, against random entries.

Each BUY/SELL pair becomes one trade of whole shares worth up to ₹40,000
(₹2,00,000 placeholder capital over five symbols), priced with the intraday
cost table. The baseline re-runs every trade 1,000 times with a random entry
bar from the same session's 09:30-11:00 window and the same holding length,
capped at 15:15. Fewer than 60 sessions or 100 trades is CAN'T TELL.
"""

import numpy as np
import pandas as pd

from autopsy.alerts.orb import BAR, SLIPPAGE, _at
from autopsy.costs import trade_costs


PER_TRADE = 40_000
MIN_SESSIONS, MIN_TRADES = 60, 100
COLUMNS = ["symbol", "day", "entry_time", "exit_time", "entry", "exit", "qty", "gross", "costs", "net", "reason"]


def _cost(side, notional, table):
    return trade_costs(side, float(notional), "intraday_equity", table).total


def trades(alerts, table):
    rows, open_ = [], {}
    for alert in sorted(alerts, key=lambda a: a.time):
        key = (alert.symbol, alert.time.normalize())
        if alert.side == "BUY":
            open_[key] = alert
            continue
        buy = open_.pop(key, None)
        qty = int(PER_TRADE // buy.price) if buy else 0
        if qty == 0:
            continue
        costs = _cost("BUY", qty * buy.price, table) + _cost("SELL", qty * alert.price, table)
        gross = qty * (alert.price - buy.price)
        rows.append({"symbol": alert.symbol, "day": key[1].date().isoformat(), "entry_time": buy.time,
                     "exit_time": alert.time, "entry": buy.price, "exit": alert.price, "qty": qty,
                     "gross": gross, "costs": costs, "net": gross - costs, "reason": alert.reason})
    return pd.DataFrame(rows, columns=COLUMNS)


def random_entries(prices, book, table, *, runs=1000, seed=0):
    """Total net PnL of each random-entry run, one value per run."""
    rng = np.random.default_rng(seed)
    totals = np.zeros(runs)
    for trade in book.itertuples():
        day = trade.entry_time.normalize()
        bars = prices[(prices["symbol"] == trade.symbol) & (prices.index.normalize() == day)].sort_index()
        closes, ends = bars["close"].to_numpy(), bars.index + BAR
        eligible = np.flatnonzero((ends > _at(day, "09:30")) & (ends <= _at(day, "11:00")))
        flat = np.flatnonzero(ends <= _at(day, "15:15"))
        if not len(eligible) or not len(flat):
            continue
        hold = int(np.searchsorted(ends, trade.exit_time) - np.searchsorted(ends, trade.entry_time))
        entry = rng.choice(eligible, runs)
        exit_ = np.minimum(entry + max(hold, 1), flat[-1])
        buy, sell = closes[entry] * (1 + SLIPPAGE), closes[exit_] * (1 - SLIPPAGE)
        qty = np.floor(PER_TRADE / buy)
        costs = np.array([_cost("BUY", q * b, table) + _cost("SELL", q * s, table) if q else 0.
                          for q, b, s in zip(qty, buy, sell)])
        totals += qty * (sell - buy) - costs
    return totals


def summarise(book, baseline, sessions):
    net = float(book["net"].sum()) if len(book) else 0.
    p95 = float(np.percentile(baseline, 95)) if len(baseline) else float("nan")
    if sessions < MIN_SESSIONS or len(book) < MIN_TRADES:
        verdict = "CAN'T TELL"
    else:
        verdict = "PASS" if net > 0 and net > p95 else "FAIL"
    return {"verdict": verdict, "sessions": sessions, "trades": len(book), "net": net,
            "gross": float(book["gross"].sum()) if len(book) else 0.,
            "costs": float(book["costs"].sum()) if len(book) else 0.,
            "win_rate": float((book["net"] > 0).mean()) if len(book) else float("nan"),
            "random_p95": p95,
            "random_share_at_least": float((baseline >= net).mean()) if len(baseline) else float("nan")}
