import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from autopsy.cli import main
from autopsy.research.trials import TrialLog


def invoke(args, root, timeout=280):
    return subprocess.run([sys.executable, '-m', 'autopsy.cli', *args],
                          env={**os.environ, 'AUTOPSY_DATA_DIR': str(root)},
                          capture_output=True, text=True, timeout=timeout)


def test_e2e_synthetic(tmp_path, monkeypatch, record_property):
    root = tmp_path / 'private'
    monkeypatch.setenv('AUTOPSY_DATA_DIR', str(root))
    start = time.monotonic()
    commands = [['data', 'synthetic'], ['research', 'run', '--mode', 'intraday'],
                ['lock', 'create'], ['holdout', 'open'],
                ['report', '--out', str(tmp_path / 'synthetic.html')]]
    for i, args in enumerate(commands):
        result = invoke(args, root, max(1, 295 - (time.monotonic() - start)))
        assert result.returncode == (1 if i >= 3 else 0), result.stdout + result.stderr
    elapsed = time.monotonic() - start
    record_property('e2e_seconds', round(elapsed, 3))
    print(f'\nSynthetic e2e runtime: {elapsed:.3f}s')
    assert elapsed < 300
    html = (tmp_path / 'synthetic.html').read_text()
    assert 'NO-GO' in html and '1,000' in html
    assert TrialLog().trial_count >= 33
    state = json.loads((root / 'session.json').read_text())
    lock_path = Path(state['lock_path'])
    header = json.loads(lock_path.read_text().splitlines()[0])
    import pandas as pd
    assert pd.Timestamp(header['locked_end']) - pd.DateOffset(months=12) == pd.Timestamp(header['locked_start'])
    assert len(lock_path.read_text().splitlines()) == 2
    # Rendering can be repeated; opening the holdout cannot.
    assert invoke(commands[-1], root).returncode == 1
    assert len(lock_path.read_text().splitlines()) == 2
    repeated = invoke(['holdout', 'open'], root)
    assert repeated.returncode == 1 and 'opened 2 times' in repeated.stdout
    assert invoke(commands[-1], root).returncode == 1
    assert 'opened 2 times' in (tmp_path / 'synthetic.html').read_text()
    lock_path.write_text(lock_path.read_text().replace('"trial_count":', '"edited_trial_count":'))
    (root / 'trials.jsonl').write_text('corrupted\n')
    damaged = invoke(commands[-1], root)
    assert damaged.returncode == 1 and 'lock integrity mismatch' in damaged.stdout
    assert 'Lifetime trial count: Unavailable' in (tmp_path / 'synthetic.html').read_text()
    evaluation = Path(state['evaluation_path'])
    evaluation.write_text(evaluation.read_text().replace('NO-GO', 'GO'))
    assert invoke(commands[-1], root).returncode == 2


def test_e2e_oracle(tmp_path):
    result = invoke(['case', 'oracle', '--report', str(tmp_path / 'oracle.html')], tmp_path / 'private')
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'ledger: FAIL' in result.stdout and 'bar 11' in result.stdout
    html = (tmp_path / 'oracle.html').read_text()
    assert 'NO-GO' in html and 'FAIL' in html and 'Reference equity' in html
    assert '160,000' in html and '10,000' in html


@pytest.mark.parametrize('args', [
    ['research', 'run', '--mode', 'intraday'], ['lock', 'create'],
    ['holdout', 'open'], ['report', '--out', 'unused.html'],
])
def test_missing_setup_is_code_two(tmp_path, monkeypatch, capsys, args):
    monkeypatch.setenv('AUTOPSY_DATA_DIR', str(tmp_path))
    assert main(args) == 2
    assert 'Traceback' not in capsys.readouterr().err


def test_import_commands(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTOPSY_DATA_DIR', str(tmp_path / 'private'))
    csv = tmp_path / 'daily.csv'
    csv.write_text('SYMBOL,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,TIMESTAMP\nSYNTH,100,101,99,100,1000,01-JAN-2025\n')
    assert main(['data', 'import-nse', str(csv)]) == 0
    fixture = Path(__file__).parent / 'fixtures/nse/announcements.csv'
    assert main(['events', 'import', str(fixture)]) == 0
    assert (tmp_path / 'private/events.jsonl').exists()
    assert main(['research', 'run', '--mode', 'intraday']) == 2


def test_no_eligible_candidate_still_renders(tmp_path, monkeypatch, capsys):
    from autopsy.data.store import save_snapshot
    from autopsy.data.synthetic import synthetic_intraday
    from autopsy.cli import _save
    monkeypatch.setenv('AUTOPSY_DATA_DIR', str(tmp_path / 'private'))
    prices = synthetic_intraday(270, 1, 'flat')
    _save({'prices_path': str(save_snapshot(prices, 'raw', 'synthetic flat')), 'source': 'synthetic flat'})
    # No fold can have a trade; isolate CLI's no-selection path from engine tests.
    monkeypatch.setattr('autopsy.cli.walk_forward', lambda *a, **k: [])
    assert main(['research', 'run', '--mode', 'intraday']) == 0
    assert "CAN'T TELL" in capsys.readouterr().out
    output = tmp_path / 'no-trades.html'
    assert main(['report', '--out', str(output)]) == 0
    assert 'NO-GO' in output.read_text() and 'No holdout was opened' in output.read_text()


def test_symbol_subset_retains_missing_bar_expectations():
    from autopsy.cli import _subset
    from autopsy.data.schedule import combine_prices
    from autopsy.data.synthetic import synthetic_intraday
    prices = synthetic_intraday(1, 1)
    etf = prices.copy()
    etf['symbol'] = 'ETF'
    combined = combine_prices([prices, etf])
    damaged = combined.drop(combined.index[1])
    result = _subset(damaged, damaged.symbol == 'ETF')
    assert len(json.loads(result.attrs['expected_bars'])) == 75
    assert len(result) == 74


def test_adjusted_basis_for_research_lock_and_benchmarks(tmp_path, monkeypatch):
    import pandas as pd
    from autopsy.cli import _save_inputs, _state
    from autopsy.data.schedule import combine_prices, with_schedule
    from autopsy.data.store import load_snapshot
    from autopsy.research.walkforward import Pick
    from autopsy.strategies import REGISTRY
    monkeypatch.setenv('AUTOPSY_DATA_DIR', str(tmp_path))
    # Two invented observations per day over development + the final 12 months.
    index = pd.date_range('2024-01-01 09:15', periods=400, tz='Asia/Kolkata')
    frame = pd.DataFrame({'symbol': 'STOCK', 'open': 100., 'high': 102., 'low': 99.,
                          'close': 101., 'volume': 100.}, index=index)
    frame = with_schedule(frame, '5min')
    frame.attrs['price_basis'] = 'adjusted'
    benchmark = frame.copy()
    benchmark['symbol'] = 'ETF'
    benchmark = with_schedule(benchmark, '5min')
    _save_inputs(combine_prices([frame, benchmark]), 'invented adjusted', benchmark=benchmark)
    state = _state()
    for key in ['prices_path', 'benchmark_path']:
        prices, meta = load_snapshot(state[key])
        assert prices.attrs['price_basis'] == meta['kind'] == 'adjusted'
    strategy = next(s for s in REGISTRY.values() if s.mode == 'intraday' and not s.data_check)
    pick = Pick(strategy.name, strategy.mode, {})
    def folds(*args, trial_log, **kwargs):
        trial_log.append(pick.strategy, {}, ['2024-01-01', '2024-02-01'], {'invented': True})
        return [object()]
    # Exercise CLI persistence only; selection maths is tested separately.
    monkeypatch.setattr('autopsy.cli.walk_forward', folds)
    monkeypatch.setattr('autopsy.cli.select', lambda _: pick)
    assert main(['research', 'run', '--mode', 'intraday', '--benchmark-symbol', 'ETF']) == 0
    state = _state()
    selected = state['selections']['intraday']
    for key in ['snapshot', 'benchmark_snapshot']:
        prices, meta = load_snapshot(selected[key])
        assert prices.attrs['price_basis'] == meta['kind'] == 'adjusted'
    assert main(['lock', 'create']) == 0
    prices, meta = load_snapshot(_state()['locked_snapshot'])
    assert prices.attrs['price_basis'] == meta['kind'] == 'adjusted'
