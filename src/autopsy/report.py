"""Offline HTML evidence: Python SVG, escaped text, and local chart/ledger links."""

from dataclasses import replace
from html import escape
import json
from math import isfinite
from pathlib import Path
import re

import numpy as np
import pandas as pd

from autopsy.costs import RateTable, trade_costs
from autopsy.ledger import replay
from autopsy.research.walkforward import GRIDS

FOOTER = 'Simulation on historical data. Not investment advice. Past results do not predict future returns.'


def _text(value):
    # Evidence may include source URLs; this artifact deliberately contains none.
    return escape(re.sub(r'https?://[^\s<>"\']+', '[source omitted]', str(value), flags=re.I), quote=True)


def _money(value):
    return 'Unavailable' if value is None or not isfinite(float(value)) else f'₹{value:,.2f}'


def _number(value):
    return 'Unavailable' if value is None or not isfinite(float(value)) else f'{value:,.4f}'


def _badge(value):
    if value not in {'PASS', 'FAIL', "CAN'T TELL", 'GO', 'NO-GO'}:
        raise ValueError('unknown verdict word')
    tone = 'good' if value in {'PASS', 'GO'} else 'bad' if value in {'FAIL', 'NO-GO'} else 'unclear'
    return f'<strong class="badge {tone}">{escape(value, quote=False)}</strong>'


def _table(headers, rows):
    return ('<div class="table-scroll" tabindex="0"><table><thead><tr>'
            + ''.join(f'<th scope="col">{_text(x)}</th>' for x in headers)
            + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')


def _row(values, attributes=''):
    return f'<tr {attributes}>' + ''.join(f'<td>{_text(v)}</td>' for v in values) + '</tr>'


def _accounting(record):
    ledger = replay(record.fills, record.prices, record.start_cash)
    opens = {(t, s): p for t, s, p in zip(record.prices.index, record.prices.symbol, record.prices.open)}
    gross_fills = [replace(f, price=float(opens[f.time, f.symbol]), fee=0.) for f in record.fills]
    gross = replay(gross_fills, record.prices, record.start_cash).equity
    return ledger, gross, opens


def _sensitivity(record, mode, opens):
    config = record.reported_equity.attrs.get('autopsy_execution')
    if not config:
        return [(bps, None) for bps in GRIDS[mode]]
    rates = RateTable(**config['rates'])
    segment = 'intraday_equity' if mode == 'intraday' else 'delivery_equity'
    result = []
    for bps in GRIDS[mode]:
        fills, sold = [], set()
        for fill in record.fills:
            price = opens[fill.time, fill.symbol] * (1 + (1 if fill.side == 'BUY' else -1) * bps / 10000)
            key = (fill.time.normalize(), fill.symbol)
            fee = trade_costs(fill.side, fill.qty * price, segment, rates, symbol_sold_today=key in sold).total
            fills.append(replace(fill, price=float(price), fee=fee))
            if fill.side == 'SELL':
                sold.add(key)
        curve = replay(fills, record.prices, record.start_cash).equity
        result.append((bps, float(curve.iloc[-1] - record.start_cash) if len(curve) else 0.))
    return result


def _chart(record, ledger, section):
    equity = record.reported_equity
    if equity.empty:
        return '<p>No equity observations.</p>'
    times = equity.index
    # Retain every fill time, alongside a bounded sampling of the full curve.
    chosen = set(np.linspace(0, len(times) - 1, min(240, len(times)), dtype=int))
    chosen.update(i for i in times.get_indexer([f.time for f in record.fills]) if i >= 0)
    indices = sorted(chosen)
    reference = ledger.equity.reindex(times)
    curves = [('Reported equity', equity, 'equity'), ('Reference equity', reference, 'reference')]
    benchmark = equity.attrs.get('nifty_etf_equity')
    if isinstance(benchmark, pd.Series) and not benchmark.empty:
        daily = benchmark.groupby(benchmark.index.normalize()).last()
        aligned = pd.Series(daily.reindex(times.normalize()).to_numpy(), index=times)
        if np.isfinite(aligned).all():
            curves.append(('Nifty 50 ETF buy-and-hold', aligned, 'benchmark'))
    values = np.concatenate([series.to_numpy(dtype=float) for _, series, _ in curves])
    low, high = float(values.min()), float(values.max())
    span = high - low or max(1., abs(high) * .01)
    low, high = low - span * .1, high + span * .1
    def x(i):
        return 90 + 770 * i / max(1, len(times) - 1)
    def y(value):
        return 240 - 210 * (value - low) / (high - low)
    parts = [f'<svg viewBox="0 0 900 280" role="img" aria-label="Equity and reference ledger chart">',
             '<title>Equity and reference ledger. Select a point to inspect its fills.</title>']
    for fraction in (0, .5, 1):
        value = low + (high - low) * fraction
        parts.append(f'<line class="grid" x1="90" x2="860" y1="{y(value):.2f}" y2="{y(value):.2f}"/>'
                     f'<text x="4" y="{y(value):.2f}">{_money(value)}</text>')
    for label, series, cls in curves:
        points = ' '.join(f'{x(i):.2f},{y(series.iloc[i]):.2f}' for i in indices)
        parts.append(f'<polyline class="{cls}" points="{points}"><title>{label}</title></polyline>')
    previous = -1
    for i in indices:
        ids = [f'fill-{section}-{j}' for j, f in enumerate(record.fills)
               if (previous < 0 or f.time > times[previous]) and f.time <= times[i]]
        label = f'{times[i].isoformat()}: {_money(equity.iloc[i])}; {len(ids)} fills'
        parts.append(f'<circle class="point" cx="{x(i):.2f}" cy="{y(equity.iloc[i]):.2f}" r="5" '
                     f'tabindex="0" role="button" aria-label="{_text(label)}" '
                     f'data-fill-ids="{_text(" ".join(ids))}" data-status="{section}"><title>{_text(label)}</title></circle>')
        previous = i
    parts.append(f'<text x="90" y="270">{times[0].date()}</text><text x="860" y="270" text-anchor="end">{times[-1].date()}</text></svg>')
    parts.append(f'<p class="chart-summary">{times[0].date()} to {times[-1].date()} · '
                 f'Equity range {_money(float(values.min()))} to {_money(float(values.max()))}.</p>')
    parts.append('<p class="legend">Reported equity · Reference equity (dashed) · Nifty 50 ETF (when available)</p>')
    if len(curves) == 2:
        parts.append('<p>Nifty 50 ETF buy-and-hold: unavailable. No substitute market return is assumed.</p>')
    return ''.join(parts)


CSS = '''
:root{color-scheme:light dark;--bg:#f3f2ed;--card:#fff;--ink:#1c2e38;--muted:#536570;--line:#d6dfdf;--good:#086355;--bad:#a13925;--accent:#176d8c;--mark:#fff0bb}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,sans-serif}main{max-width:1120px;margin:auto;padding:36px 24px}header{border-bottom:2px solid var(--ink);padding-bottom:24px}h1{font-size:clamp(2rem,5vw,3.4rem);line-height:1.1;letter-spacing:-.04em;margin:.3em 0}h2{font-size:1.5rem;line-height:1.3}h3{font-size:1.1rem;margin-top:28px}.eyebrow{letter-spacing:.13em;font-size:.75rem;text-transform:uppercase;color:var(--muted)}.muted,.legend,footer{color:var(--muted)}section{margin-top:28px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:24px;min-width:0}p,li,td,pre{overflow-wrap:anywhere}.strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:10px}.cell{border:1px solid var(--line);border-radius:8px;padding:12px}.cell span{display:block;margin-bottom:7px}.badge{display:inline-block;font-size:.85rem;letter-spacing:.04em}.good{color:var(--good)}.bad{color:var(--bad)}.unclear{color:var(--muted)}.hero{font-size:1.7rem}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px}.metric b{display:block;font-size:1.45rem;font-variant-numeric:tabular-nums}.table-scroll{max-width:100%;overflow:auto;border:1px solid var(--line);border-radius:8px}table{border-collapse:collapse;width:100%;font-size:.85rem}th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}th{color:var(--muted)}tr.selected{background:var(--mark);outline:2px solid var(--accent);outline-offset:-2px}svg{display:block;width:100%;height:auto;min-height:170px}svg text{fill:var(--muted);font-size:12px}.grid{stroke:var(--line)}polyline{fill:none;stroke-width:2.4}.equity{stroke:var(--accent)}.reference{stroke:var(--good);stroke-dasharray:5 4}.benchmark{stroke:#b18222}.point{fill:transparent;stroke:none;cursor:pointer}.point:hover,.point:focus{fill:var(--accent);stroke:var(--card);stroke-width:2;outline:none}.legend{font-size:.85rem}input{font:inherit;width:5.5em;padding:6px;border:1px solid var(--line);border-radius:5px;background:var(--card);color:var(--ink)}summary{cursor:pointer}pre{white-space:pre-wrap;font-size:.8rem}footer{padding:36px 0;font-size:.85rem}
@media(max-width:480px){main{padding:20px 12px}section{padding:16px 12px}h1{font-size:2.25rem}.strip{grid-template-columns:repeat(2,minmax(0,1fr))}.metrics{grid-template-columns:1fr}th,td{padding:8px}.table-scroll{font-size:.8rem}svg text{display:none}}
@media(prefers-color-scheme: dark){:root{--bg:#101a20;--card:#18272f;--ink:#e4eeed;--muted:#adbfca;--line:#354953;--good:#71d5b6;--bad:#ffae94;--accent:#8ad2f0;--mark:#54451f}}
@media print{section{break-inside:avoid}.table-scroll{overflow:visible}body{background:white}input{border:0}}
'''
JS = '''
document.querySelectorAll('[data-fill-ids]').forEach(point=>{
 const select=()=>{document.querySelectorAll('tr.selected').forEach(row=>row.classList.remove('selected'));
 const ids=point.dataset.fillIds.split(' ').filter(Boolean);
 ids.forEach(id=>document.getElementById(id)?.classList.add('selected'));
 document.getElementById('status-'+point.dataset.status).textContent=ids.length?ids.length+' fills highlighted below.':'No fills in this interval.';
 if(ids.length)document.getElementById(ids[0]).scrollIntoView({block:'center',behavior:'smooth'});};
 point.addEventListener('click',select);point.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select();}});
});
document.querySelectorAll('[data-tax-base]').forEach(input=>{
 const update=()=>{const rate=Number(input.value);if(!Number.isFinite(rate)||rate<0||rate>100)return;
 const tax=Number(input.dataset.taxBase)*rate/100;
 document.getElementById(input.dataset.output).textContent='₹'+tax.toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});};
 input.addEventListener('input',update);
});
'''


def render_report(verdicts, records, trial_log, out_path, *, slab_rate=30):
    """Render aligned Verdict/RunRecord sequences (or matching keyed mappings).

    Optional stats keys: title, mode, notes. Equity attrs may contain an actual
    nifty_etf_equity series, funded at the same capital, for comparison. Costs
    are repriced holding observed fills/quantities constant; this descriptive
    sensitivity never replaces the verdict's doubled-slippage execution.
    """
    if not isfinite(slab_rate) or not 0 <= slab_rate <= 100:
        raise ValueError('slab rate must be a percentage from 0 to 100')
    if isinstance(verdicts, dict):
        records = [records[key] for key in verdicts]
        verdicts = list(verdicts.values())
    else:
        verdicts, records = list(verdicts), list(records)
    if not verdicts or len(verdicts) != len(records):
        raise ValueError('one record per verdict required')
    rows = trial_log.rows() if hasattr(trial_log, 'rows') else list(trial_log or [])
    trials = ('Unavailable' if trial_log is None else
              sum(row.get('metrics', {}).get('status') != 'complete' for row in rows))
    overall = 'GO' if all(v.verdict == 'GO' for v in verdicts) else 'NO-GO'
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<title>Oracle Autopsy · Research report</title><style>', CSS, '</style></head><body><main>',
             '<header><p class="eyebrow">Oracle Autopsy / Local research</p><h1>Every result needs evidence.</h1>',
             f'<p class="hero">{_badge(overall)}</p><p>Historical simulation. Checks first, returns second.</p></header>']
    for index, (verdict, record) in enumerate(zip(verdicts, records)):
        mode = verdict.stats.get('mode', record.reported_equity.attrs.get('autopsy_execution', {}).get('mode', 'intraday'))
        ledger, gross, opens = _accounting(record)
        net = float(ledger.equity.iloc[-1] - record.start_cash) if len(ledger) else 0.
        gross_pnl = float(gross.iloc[-1] - record.start_cash) if len(gross) else 0.
        reported = float(record.reported_equity.iloc[-1]) if len(record.reported_equity) else record.start_cash
        title = verdict.stats.get('title', f'{mode.capitalize()} research')
        parts.append(f'<section><h2>{_text(title)}</h2><div class="strip"><div class="cell"><span>Overall</span>{_badge(verdict.verdict)}</div>')
        for check in verdict.checks:
            parts.append(f'<div class="cell"><span>{_text(check.name.replace("_", " ").capitalize())}</span>{_badge(check.verdict)}</div>')
        parts.append('</div>')
        if verdict.reasons:
            parts.append('<ul>' + ''.join(f'<li>{_text(reason)}</li>' for reason in verdict.reasons) + '</ul>')
        for note in verdict.stats.get('notes', []):
            parts.append(f'<p class="muted">{_text(note)}</p>')
        if verdict.stats.get('survivorship_bias'):
            parts.append(f'<p class="muted">{_text(verdict.stats["survivorship_bias"])}</p>')
        nifty50 = verdict.stats.get('nifty50_buy_and_hold')
        if nifty50 is not None:
            parts.append(f'<p>Nifty 50 buy-and-hold (context only): {_money(nifty50["net_profit"])}; '
                         f'Sharpe {_number(nifty50["sharpe"])}. {_text(nifty50["basis"])}</p>')
        parts.append('<h3>Equity against the reference ledger</h3>')
        parts.append(_chart(record, ledger, index))
        parts.append('<p>Nifty 50 ETF: context, not a gate. When available, buy-and-hold is normalized to starting capital, before ETF costs and tax.</p>')
        parts.append('<div class="metrics">' + ''.join(f'<div class="metric">{label}<b>{_money(value)}</b></div>' for label, value in [
            ('Starting capital', record.start_cash), ('Reported final equity', reported),
            ('Reference final equity', float(ledger.equity.iloc[-1]) if len(ledger) else record.start_cash),
            ('Gross result', gross_pnl), ('Net result before tax', net), ('Fees and slippage', gross_pnl - net)]) + '</div>')
        parts.append('<p class="muted">Gross and net use the same fills and whole-share quantities. Gross removes fees and slippage; net comes from the reference ledger.</p>')
        parts.append('<h3>Cost sensitivity</h3>')
        sensitivity = _sensitivity(record, mode, opens)
        parts.append(_table(['Slippage per side', 'Net result before tax', 'Edge'], [
            _row([f'{bps} bps', _money(pnl), 'Unavailable' if pnl is None else 'Above zero' if pnl > 0 else 'At or below zero'])
            for bps, pnl in sensitivity]))
        vanished = next((bps for bps, pnl in sensitivity if pnl is not None and pnl <= 0), None)
        parts.append('<p>' + (f'The edge is at or below zero at {vanished} bps per side.' if vanished is not None else
                     'Sensitivity is unavailable for this case.' if all(pnl is None for _, pnl in sensitivity) else
                     'No crossing observed in the available grid.') + ' Quantities and trade times stay fixed.</p>')
        bps = verdict.stats.get('slippage_bps', record.reported_equity.attrs.get('autopsy_execution', {}).get('slippage_bps'))
        parts.append(f'<p>Gating execution: {_number(bps)} bps per side; doubled base slippage, before tax.</p>'
                     if bps is not None else '<p>No production gating execution. This is a bug demonstration.</p>')
        parts.append('<h3>Tax illustration</h3><p>Never part of the verdict. Applied only to positive net results; losses receive no tax credit in this illustration.</p>')
        if mode == 'intraday':
            parts.append(f'<p>Intraday business income. <label for="slab-{index}">Slab rate (%)</label> '
                         f'<input id="slab-{index}" type="number" min="0" max="100" step="0.1" value="{slab_rate:g}" '
                         f'data-tax-base="{max(0., net):.8f}" data-output="tax-{index}"> '
                         f'Illustrative tax: <output id="tax-{index}">{_money(max(0., net) * slab_rate / 100)}</output>.</p>')
        else:
            parts.append(f'<p>Swing: 20% short-term capital gains (STCG). Illustrative tax: {_money(max(0., net) * .2)}.</p>')
        parts.append(f'<h3>Selection and statistical evidence</h3><p>Lifetime trial count: {trials}. '
                     f'Deflated Sharpe: {_number(verdict.stats.get("dsr"))} (heuristic).</p>')
        if verdict.stats.get('random_entry_runs'):
            parts.append(f'<p>{verdict.stats["random_entry_runs"]:,} random-entry runs; 95th percentile: '
                         f'{_money(verdict.stats.get("random_entry_p95"))}. One-sided 95% bootstrap lower bound: '
                         f'{_money(verdict.stats.get("bootstrap_lower"))} per day.</p>')
        parts.append('<details><summary>Check evidence</summary>' + ''.join(
            f'<h3>{_text(c.name.replace("_", " ").capitalize())}</h3><pre>{_text(json.dumps(c.evidence, default=str, indent=2))}</pre>'
            for c in verdict.checks) + '</details>')
        parts.append(f'<h3>Fill ledger</h3><p id="status-{index}" role="status">Select a chart point to highlight the fills since the previous point.</p>')
        fills = []
        for j, f in enumerate(record.fills):
            bar = ledger.loc[f.time]
            fills.append(_row([f.time.isoformat(), f.symbol, f.side, f.qty, _money(f.price), _money(f.fee),
                               _money(bar.cash), _money(bar.holdings_value), _money(bar.equity)], f'id="fill-{index}-{j}"'))
        parts.append(_table(['Time (IST)', 'Symbol', 'Side', 'Shares', 'Price', 'Fee', 'Cash', 'Holdings', 'Equity'], fills))
        parts.append('<p class="muted">Cash, holdings and equity are after all fills at that timestamp.</p></section>')
    parts.append('<section><h2>Trial log</h2><details><summary>Inspect lifetime attempts and outcomes</summary>')
    parts.append(_table(['Strategy', 'Parameters', 'Window', 'Metrics'], [_row([
        row.get('strategy', ''), json.dumps(row.get('params', {})), str(row.get('window', '')),
        json.dumps(row.get('metrics', {}), default=str)]) for row in rows]))
    parts.append(f'</details></section><footer>{FOOTER}</footer></main><script>{JS}</script></body></html>')
    path = Path(out_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(parts), encoding='utf-8')
    return path
