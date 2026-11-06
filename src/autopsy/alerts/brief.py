"""Evening brief for the owner: a short market strip from read-only Kite data.

Only the Nifty 200-day regime is a strategy input; everything else is context
(see docs/research/2026-11-05-daily-brief-research.md). No news, no tips, no
scores. Paper only; not investment advice.
"""

import pandas as pd

INDEX = "NSE:NIFTY 50"
VIX = "NSE:INDIA VIX"
DEFAULT_STATUS = ("none has passed yet (6 versions tested on real data, all rejected). "
                  "Next: monthly momentum, waiting for historical index membership.")
LOGIN_NEEDED = ("Oracle Autopsy: no brief tonight, the Kite login has expired. "
                "Run `autopsy kite login` on your Mac, then `autopsy brief`.")


def _pct(last, prev):
    return (last / prev - 1) * 100 if prev else None


def _name(symbol):
    return symbol.split(":", 1)[1]


def format_brief(quotes, index_closes, *, now, status=DEFAULT_STATUS, index=INDEX, vix=VIX, headlines=None):
    """quotes: {symbol: {last_price, prev_close, last_trade_time}} from KiteClient.quotes.
    index_closes: daily index closes (Series indexed by date) before today."""
    now = pd.Timestamp(now).tz_convert("Asia/Kolkata")
    stocks = {s: q for s, q in quotes.items() if s not in (index, vix)}
    traded = [q["last_trade_time"] for q in stocks.values() if q["last_trade_time"] is not None]
    session = max(traded).date() if traded else now.date()
    lines = [f"Oracle Autopsy · {now:%a %d %b %Y, %H:%M} IST"]
    if session != now.date():
        lines.append(f"Market closed today. Figures are from {pd.Timestamp(session):%a %d %b}.")
    if index in quotes:
        last = quotes[index]["last_price"]
        line = f"Nifty 50 {last:,.2f} ({_pct(last, quotes[index]['prev_close']):+.2f}%)"
        closes = pd.Series(index_closes, dtype=float)
        closes = closes[[pd.Timestamp(d).date() < session for d in closes.index]]
        history = pd.concat([closes, pd.Series([last])], ignore_index=True)
        if len(history) >= 200:
            average = history.iloc[-200:].mean()
            side = "above" if last > average else "below"
            line += f", {side} its 200-day average {average:,.0f} (regime {'ON' if side == 'above' else 'OFF'})"
        else:
            line += ", 200-day regime unknown (not enough history)"
        lines.append(line)
    if vix in quotes:
        q = quotes[vix]
        lines.append(f"India VIX {q['last_price']:.2f} ({_pct(q['last_price'], q['prev_close']):+.2f}%)")
    moves = {s: _pct(q["last_price"], q["prev_close"]) for s, q in stocks.items()}
    moves = {s: m for s, m in moves.items() if m is not None}
    if moves:
        ranked = sorted(moves, key=lambda s: (moves[s], s))
        up = sum(m > 0 for m in moves.values())
        down = sum(m < 0 for m in moves.values())
        lines.append(f"Tracked stocks: {up} up, {down} down of {len(moves)}")
        lines.append("Top: " + ", ".join(f"{_name(s)} {moves[s]:+.1f}%" for s in reversed(ranked[-3:])))
        lines.append("Bottom: " + ", ".join(f"{_name(s)} {moves[s]:+.1f}%" for s in ranked[:3]))
    if headlines is not None:
        if headlines:
            lines.append("News (Economic Times, context only):")
            lines.extend(f"- {item['title']} {item['link']}" for item in headlines)
        else:
            lines.append("News: unavailable tonight.")
    lines.append(f"Strategy: {status}")
    lines.append("Paper only. Not investment advice.")
    return "\n".join(lines)


def daily_brief(client, symbols, *, now=None, status=DEFAULT_STATUS, index=INDEX, vix=VIX, headlines=None):
    """Fetch read-only quotes and index history with a KiteClient; return the text."""
    now = pd.Timestamp.now(tz="Asia/Kolkata") if now is None else pd.Timestamp(now).tz_convert("Asia/Kolkata")
    quotes = client.quotes(list(dict.fromkeys([*symbols, index, vix])))
    history = client.candles(index, "day", (now - pd.Timedelta(days=420)).date(),
                             (now - pd.Timedelta(days=1)).date())
    closes = pd.Series(history["close"].to_numpy(), index=history.index.normalize())
    return format_brief(quotes, closes, now=now, status=status, index=index, vix=vix, headlines=headlines)
