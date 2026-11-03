"""Single-file, offline HTML page for paper alerts: phone feed, session charts, scorecard."""

from html import escape
from math import isfinite

from autopsy.alerts.notify import format_alert
from autopsy.alerts.orb import BAR
from autopsy.report import CSS, _badge, _money, _row, _table, _text


PAGE_CSS = '''
.lede{max-width:62ch;color:var(--muted)}
.score{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}
.score div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.score b{display:block;font-size:1.35rem;font-variant-numeric:tabular-nums}.score span{color:var(--muted);font-size:.85rem}
.split{display:grid;grid-template-columns:minmax(260px,340px) 1fr;gap:28px;align-items:start}
.phone{background:#0d1418;border-radius:34px;padding:18px 12px 22px;box-shadow:0 0 0 6px #26343c inset}
.phone .clock{color:#e4eeed;text-align:center;font-size:2.4rem;font-weight:300;margin:6px 0 14px;font-variant-numeric:tabular-nums}
.note{background:rgba(228,238,237,.94);color:#1c2e38;border-radius:14px;padding:10px 12px;margin:8px 0;font-size:.84rem;line-height:1.4}
.note small{display:flex;justify-content:space-between;color:#536570;font-size:.72rem;margin-bottom:3px}
.note.buy{border-left:5px solid #086355}.note.sell{border-left:5px solid #a13925}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
.charts figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}
.charts figcaption{font-weight:600;display:flex;justify-content:space-between}.charts figcaption span{font-weight:400;color:var(--muted)}
.charts svg{width:100%;height:auto;display:block}
@media(max-width:720px){.split{grid-template-columns:1fr}}
'''


def _chart(symbol, bars, alerts):
    width, height, pad = 320, 150, 8
    closes = bars["close"].to_list()
    opening = bars.iloc[:3]
    high, low = float(opening["high"].max()), float(opening["low"].min())
    prices = closes + [high, low] + [a.price for a in alerts]
    top, bottom = max(prices), min(prices)
    span = (top - bottom) or 1.
    x = lambda i: pad + i * (width - 2 * pad) / max(len(closes) - 1, 1)
    y = lambda p: pad + (top - p) * (height - 2 * pad) / span
    index = {time: i for i, time in enumerate(bars.index + BAR)}
    line = " ".join(f"{x(i):.1f},{y(c):.1f}" for i, c in enumerate(closes))
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(symbol)} session with range and paper fills">',
             f'<rect x="{x(0):.1f}" y="{pad}" width="{x(2) - x(0):.1f}" height="{height - 2 * pad}" fill="var(--mark)"/>',
             f'<line x1="{pad}" x2="{width - pad}" y1="{y(high):.1f}" y2="{y(high):.1f}" stroke="var(--good)" stroke-dasharray="4 3"/>',
             f'<line x1="{pad}" x2="{width - pad}" y1="{y(low):.1f}" y2="{y(low):.1f}" stroke="var(--bad)" stroke-dasharray="4 3"/>',
             f'<polyline points="{line}" fill="none" stroke="var(--ink)" stroke-width="1.5"/>']
    for alert in alerts:
        i = index.get(alert.time, len(closes) - 1)
        cx, cy = x(i), y(alert.price)
        if alert.side == "BUY":
            parts.append(f'<path d="M{cx:.1f},{cy - 7:.1f} l6,10 h-12z" fill="var(--good)"/>')
        else:
            parts.append(f'<path d="M{cx:.1f},{cy + 7:.1f} l6,-10 h-12z" fill="var(--bad)"/>')
    parts.append('</svg>')
    return "".join(parts)


def render_alerts_page(alerts, prices, book, summary, out_path, *, source):
    traded_days = sorted({a.time.normalize() for a in alerts})
    day = traded_days[-1] if traded_days else None
    todays = [a for a in alerts if day is not None and a.time.normalize() == day]
    feed = "".join(
        f'<div class="note {a.side.lower()}"><small><span>Oracle Autopsy · paper</span>'
        f'<span>{a.time:%H:%M}</span></small>{_text(format_alert(a))}</div>' for a in todays)
    charts = []
    for symbol in sorted({a.symbol for a in todays}):
        bars = prices[(prices["symbol"] == symbol) & (prices.index.normalize() == day)].sort_index()
        mine = [a for a in todays if a.symbol == symbol]
        result = book[(book["symbol"] == symbol) & (book["day"] == day.date().isoformat())]["net"].sum()
        charts.append(f'<figure><figcaption>{_text(symbol)}<span>net {_money(result)}</span></figcaption>'
                      f'{_chart(symbol, bars, mine)}</figure>')
    pct = summary["random_share_at_least"]
    beaten = f"{pct:.0%}" if isfinite(pct) else "Unavailable"
    rows = [_row([t.day, t.symbol, f"{t.entry_time:%H:%M}", _money(t.entry), f"{t.exit_time:%H:%M}",
                  _money(t.exit), t.qty, t.reason, _money(t.costs), _money(t.net)])
            for t in book.iloc[::-1].head(40).itertuples()]
    html = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>Oracle Autopsy · Paper alerts</title><style>', CSS, PAGE_CSS, '</style></head><body><main>',
        '<header><p class="eyebrow">Paper alerts · 15-minute opening-range breakout</p>',
        f'<h1>{summary["trades"]} paper trades, {summary["sessions"]} sessions</h1>',
        f'<p class="lede">Source: {_text(source)}. Buy when a stock closes above its 09:15–09:30 high before 11:00; '
        'sell below the range low, at twice the risk, or at 15:15. Fills include 5 bps slippage and the full Indian '
        'intraday cost table. Paper only: this tool never places orders and none of this is investment advice.</p></header>',
        f'<section><h2>Scorecard {_badge(summary["verdict"])}</h2><div class="score">',
        f'<div><b>{_money(summary["net"])}</b><span>net after costs</span></div>',
        f'<div><b>{_money(summary["costs"])}</b><span>taxes and charges paid</span></div>',
        f'<div><b>{summary["win_rate"]:.0%}</b><span>winning trades</span></div>' if isfinite(summary["win_rate"]) else '',
        f'<div><b>{beaten}</b><span>of 1,000 random-entry runs did at least as well</span></div></div>',
        '<p>CAN\'T TELL until 60 sessions and 100 trades. After that it must beat the 95th percentile of random entries to PASS.</p></section>',
    ]
    if day is not None:
        html += [f'<section><h2>{day:%A %d %B %Y}</h2><div class="split">',
                 f'<div class="phone" aria-label="Alerts as they arrive on the phone"><div class="clock">15:15</div>{feed}</div>',
                 f'<div><div class="charts">{"".join(charts)}</div>',
                 '<p class="legend">Shaded: opening range. Dashed: range high (green) and low (red). Triangles: paper buy and sell.</p></div>',
                 '</div></section>']
    html += ['<section><h2>Recent paper trades</h2>',
             _table(["Day", "Symbol", "In", "Buy", "Out", "Sell", "Qty", "Exit", "Costs", "Net"], rows),
             '</section></main></body></html>']
    text = "".join(html)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return out_path
