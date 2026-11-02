import re
from html import unescape

import pandas as pd
import pytest

from autopsy.checks import CheckResult
from autopsy.costs import load_rates
from autopsy.data.synthetic import synthetic_intraday
from autopsy.engine import Signal, run_backtest
from autopsy.report import render_report
from autopsy.research.trials import TrialLog
from autopsy.verdict import Verdict

FOOTER = 'Simulation on historical data. Not investment advice. Past results do not predict future returns.'


@pytest.fixture
def report(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTOPSY_DATA_DIR', str(tmp_path / 'private'))
    prices = synthetic_intraday(2, 17)
    record = run_backtest(prices, [Signal(prices.index[0], 'SYNTH', 1)],
                          'intraday', slippage_bps=20, rates=load_rates('zerodha'))
    verdict = Verdict('NO-GO', ['Too few trades.'],
                      [CheckResult('trades', "CAN'T TELL", {'trades': 1})], {'dsr': None})
    return verdict, record, TrialLog(), tmp_path / 'report.html'


def test_report_offline(report):
    path = render_report([report[0]], [report[1]], report[2], report[3])
    html = path.read_text()
    assert not re.search(r'https?://|src=|@import|fetch\(', html, re.I)
    assert '<svg' in html and '<style>' in html and '<script>' in html
    assert 'prefers-color-scheme: dark' in html and 'width=device-width' in html
    assert 'data-fill-ids=' in html and 'id="fill-0-0"' in html


def test_report_footer_present(report):
    assert FOOTER in render_report([report[0]], [report[1]], report[2], report[3]).read_text()


def test_no_profit_language(report):
    html = render_report([report[0]], [report[1]], report[2], report[3]).read_text()
    text = unescape(re.sub('<[^>]*>', ' ', html)).lower()
    assert not any(word in text for word in ['guaranteed', 'sure', 'profit assured', 'recommend'])


def test_tax_and_html_escaping(report):
    verdict, record, log, path = report
    verdict.reasons = ['<script>alert(1)</script> https://example.invalid']
    html = render_report([verdict], [record], log, path, slab_rate=15).read_text()
    assert '<script>alert(1)' not in html and 'https://' not in html
    assert 'business income' in html and 'value="15"' in html
    assert 'Never part of the verdict' in html
    with pytest.raises(ValueError):
        render_report([verdict], [record], log, path, slab_rate=101)


def test_swing_tax_and_benchmark(report):
    verdict, record, log, path = report
    record.reported_equity.attrs['autopsy_execution']['mode'] = 'swing'
    record.reported_equity.attrs['nifty_etf_equity'] = pd.Series(
        [200000., 201000.], index=record.prices.index.normalize().unique())
    html = render_report([verdict], [record], log, path).read_text()
    assert '20% short-term capital gains' in html
    assert 'class="benchmark"' in html
