"""Local research workflow. All persistent inputs and audit state are private."""

import argparse
from dataclasses import asdict
from itertools import product
import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

import pandas as pd

from autopsy.checks import CheckResult
from autopsy.costs import load_rates
from autopsy.data.nse import load_bhavcopy
from autopsy.data.schedule import combine_prices, with_schedule
from autopsy.data.store import data_dir, load_snapshot, save_snapshot
from autopsy.data.synthetic import synthetic_intraday
from autopsy.data.upstox import DEFAULT_TOKEN_PATH, TokenMissing, UpstoxClient, UpstoxError
from autopsy.engine import run_backtest
from autopsy.news.events import EventLedger, with_events
from autopsy.news.nse_filings import load_nse_announcements, load_nse_deals
from autopsy.report import render_report
from autopsy.research.lock import Lock, hash_prices
from autopsy.research.trials import TrialLog, _digest, _line_hash, _read
from autopsy.research.walkforward import GRIDS, Pick, select, walk_forward
from autopsy.stats import MinTradesError
from autopsy.strategies import REGISTRY, registry_hash
from autopsy.types import Fill, RunRecord
from autopsy.verdict import Verdict, decide


class SetupError(ValueError):
    pass


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name('.' + uuid4().hex + '.tmp')
    try:
        with temp.open('x', encoding='utf-8') as stream:
            temp.chmod(0o600)
            json.dump(value, stream, indent=2, allow_nan=False, default=str)
            stream.write('\n')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _state():
    path = data_dir() / 'session.json'
    return json.loads(path.read_text()) if path.exists() else {}


def _save(state):
    _write(data_dir() / 'session.json', state)


def _read_lock(path):
    # Inspection must never call Lock.open: only the explicit command opens it.
    with Path(path).open(encoding='utf-8') as stream:
        rows = _read(stream)
    if not rows or rows[0].get('kind') != 'lock':
        raise SetupError('Invalid lock journal.')
    return Lock(path, rows[0])


def _inputs(state):
    if 'prices_path' not in state:
        raise SetupError('Missing price data. Run autopsy data synthetic, import-nse or fetch-upstox first.')
    return load_snapshot(state['prices_path'])[0]


def _save_inputs(prices, source, *, benchmark=None):
    if prices.empty:
        raise SetupError('No price observations were loaded.')
    state = _state()
    state.update(prices_path=str(save_snapshot(prices, 'raw', source)), source=source, selections={})
    state.pop('benchmark_path', None)
    if benchmark is not None:
        state['benchmark_path'] = str(save_snapshot(benchmark, 'raw', source + ' benchmark'))
    _save(state)
    print(state['prices_path'])


def _archive(paths, directory):
    target = data_dir() / directory
    target.mkdir(parents=True, exist_ok=True)
    for path in paths:
        shutil.copyfile(path, target / (uuid4().hex + '.csv'))


def _data(args):
    if args.data_command == 'synthetic':
        # Short, invented sessions are an explicit CPU demo, not NSE sessions.
        prices = synthetic_intraday(args.days, args.seed)
        prices = with_schedule(prices.groupby(prices.index.normalize(), sort=False).head(15), '5min')
        prices.attrs['source'] = 'synthetic random walk; invented 09:15–10:25 sessions'
        _save_inputs(prices, prices.attrs['source'])
    elif args.data_command == 'import-nse':
        prices = load_bhavcopy(args.csv)
        _archive(args.csv, 'nse')
        _save_inputs(prices, 'Manually imported NSE daily files')
    else:
        # Keep token validation first, including the Task 9 monkeypatch point.
        client = UpstoxClient(token_path=args.token_path)
        symbols = [line.strip() for line in Path(args.symbols).read_text().splitlines() if line.strip()]
        prices = combine_prices([client.candles(symbol, args.unit, args.interval, args.start, args.end)
                                 for symbol in symbols])
        _save_inputs(prices, 'Upstox V3 historical candles')
    return 0


def _events(args):
    events = (load_nse_announcements(args.csv) if args.kind == 'announcements'
              else load_nse_deals(args.csv, kind=args.kind))
    log = EventLedger()
    for event in events:
        log.add(event)
    _archive(args.csv, 'nse/events')
    print(f'Imported {len(events)} event rows; the ledger deduplicates repeated documents.')
    return 0


def _research(args):
    state = _state()
    prices = _inputs(state)
    benchmark = None
    if args.benchmark_symbol:
        benchmark = _subset(prices, prices.symbol == args.benchmark_symbol)
        prices = _subset(prices, prices.symbol != args.benchmark_symbol)
        if benchmark.empty or prices.empty:
            raise SetupError('Benchmark symbol and at least one trading symbol must be present.')
    if args.mode == 'intraday' and prices.attrs.get('bar_interval') != '5min':
        raise SetupError('Intraday strategies require five-minute data; daily NSE files cannot validate them.')
    end = prices.index.max().normalize() + pd.Timedelta(days=1)
    start = end - pd.DateOffset(months=12)
    dev = prices.loc[prices.index < start]
    if dev.empty or len(dev.index.normalize().unique()) < 4:
        raise SetupError('Need development sessions before the locked final 12 months.')
    # Attach only an explicitly imported ledger. Absence is unknown coverage.
    event_log = EventLedger()
    if event_log.path.exists():
        prices = with_events(prices, event_log.events())
    dev = prices.loc[prices.index < start]
    log = TrialLog()
    results = []
    for strategy in REGISTRY.values():
        if strategy.mode != args.mode:
            continue
        print(f'Research: {strategy.name}', file=sys.stderr, flush=True)
        check = strategy.data_check(dev) if strategy.data_check else None
        if check is not None and check.verdict != 'PASS':
            # Log every rejected combination without repeatedly simulating
            # impossible trades. No absent event evidence becomes known empty.
            keys = sorted(strategy.params_grid)
            for values in product(*(strategy.params_grid[key] for key in keys)):
                for bps in GRIDS[strategy.mode]:
                    log.append(strategy.name, dict(zip(keys, values)),
                               [dev.index.min().isoformat(), start.isoformat()],
                               {'status': 'unavailable', 'base_slippage_bps': bps,
                                'verdict': check.verdict, 'data_check': check.evidence})
            continue
        results.extend(walk_forward(strategy, prices, start, trial_log=log))
    try:
        if not results:
            raise MinTradesError('no usable development folds')
        pick = select(results)
    except MinTradesError:
        state.setdefault('selections', {}).pop(args.mode, None)
        record = run_backtest(dev, [], args.mode, slippage_bps=2 * GRIDS[args.mode][0], rates=load_rates('zerodha'))
        verdict = Verdict('NO-GO', ['No candidate has 30 completed trades in every development fold.'],
                          [CheckResult('selection', "CAN'T TELL", {'reason': 'No usable development candidate'})],
                          {'mode': args.mode, 'title': 'Development selection / No eligible strategy',
                           'notes': ['No holdout was opened. This empty ledger shows development coverage only.']})
        preview = {'verdicts': [asdict(verdict)], 'records': [_encode_record(record)],
                   'snapshot': str(save_snapshot(dev, 'raw', 'Development-only selection evidence'))}
        path = data_dir() / 'evaluations' / (uuid4().hex + '.json')
        _write(path, preview)
        state['preview_path'] = str(path)
        _save(state)
        print("Selection: CAN'T TELL. No candidate has 30 completed trades in every development fold. NO-GO.")
        return 0
    # Freeze event evidence with prices; later imports cannot rewrite selection.
    snapshot = save_snapshot(prices, 'raw', state['source'] + '; research input')
    state.setdefault('selections', {})[args.mode] = {
        'pick': asdict(pick), 'snapshot': str(snapshot), 'input_path': state['prices_path'],
        'registry_hash': registry_hash(), 'trial_head': log.head,
        'locked_start': start.isoformat(), 'locked_end': end.isoformat(),
        'development_hash': hash_prices(dev),
        'benchmark_snapshot': str(save_snapshot(benchmark, 'raw', 'Owner-identified Nifty 50 ETF')) if benchmark is not None else None,
    }
    state.pop('preview_path', None)
    _save(state)
    print(f'Selected {pick.strategy} ({args.mode}) using development folds only. Lifetime trials: {log.trial_count}.')
    return 0


def _subset(prices, mask):
    """Filter symbols without reconstructing or weakening expected coverage."""
    result = prices.loc[mask].copy()
    symbols = set(result.symbol)
    result.attrs['expected_bars'] = json.dumps([pair for pair in json.loads(prices.attrs['expected_bars'])
                                               if pair[1] in symbols], separators=(',', ':'))
    return result


def _create_lock():
    state, log = _state(), TrialLog()
    selections = list(state.get('selections', {}).values())
    if not selections:
        raise SetupError('No selected strategy. Run autopsy research run with enough development trades first.')
    windows = {(s['locked_start'], s['locked_end']) for s in selections}
    if len(windows) != 1:
        raise SetupError('Selected modes must share the same locked window.')
    start, end = next(iter(windows))
    locked_frames, picks = [], []
    for selection in selections:
        prices, _ = load_snapshot(selection['snapshot'])
        if (selection['registry_hash'] != registry_hash() or selection['input_path'] != state['prices_path']
                or selection['development_hash'] != hash_prices(prices.loc[prices.index < pd.Timestamp(start)])
                or not any(_line_hash(row) == selection['trial_head'] for row in log.rows())):
            raise SetupError('Selection provenance changed. Run development research again.')
        locked_frames.append(prices.loc[(prices.index >= pd.Timestamp(start)) & (prices.index < pd.Timestamp(end))])
        picks.append(Pick(**selection['pick']))
    hashes = {hash_prices(frame) for frame in locked_frames}
    if len(hashes) != 1 or locked_frames[0].empty:
        raise SetupError('Selected modes must share identical locked price and event evidence.')
    directory = data_dir() / 'locks'
    for old_path in directory.glob('*.jsonl'):
        old = _read_lock(old_path)
        if pd.Timestamp(start) < old.locked_end:
            raise SetupError('This holdout window overlaps a previous lock. Existing locked months cannot be selected again.')
    path = directory / (pd.Timestamp(end).strftime('%Y%m%d') + '.jsonl')
    lock = Lock.create(path, next(iter(hashes)), registry_hash(), picks, log.head,
                       locked_start=start, locked_end=end, trial_log_path=log.path)
    state['lock_path'] = str(lock.path)
    state['locked_snapshot'] = str(save_snapshot(locked_frames[0], 'raw', 'Sealed holdout input'))
    state['locked_source'] = state['source']
    state['locked_benchmark'] = selections[0].get('benchmark_snapshot')
    state.pop('evaluation_path', None)
    _save(state)
    print(f'Locked {start} to {end} (exclusive). Selection rule: {lock.selection_rule}.')
    return 0


def _encode_record(record):
    attrs = dict(record.reported_equity.attrs)
    benchmark = attrs.pop('nifty_etf_equity', None)
    return {'fills': [asdict(fill) for fill in record.fills], 'start_cash': record.start_cash,
            'equity': [[t.isoformat(), float(v)] for t, v in record.reported_equity.items()],
            'equity_attrs': attrs,
            'benchmark': [[t.isoformat(), float(v)] for t, v in benchmark.items()] if benchmark is not None else None}


def _decode_record(row, prices):
    fills = [Fill(**dict(fill, time=pd.Timestamp(fill['time']))) for fill in row['fills']]
    equity = pd.Series([value for _, value in row['equity']],
                       index=pd.DatetimeIndex([time for time, _ in row['equity']]).tz_convert('Asia/Kolkata'), name='equity')
    equity.attrs = row['equity_attrs']
    if row.get('benchmark'):
        equity.attrs['nifty_etf_equity'] = pd.Series([v for _, v in row['benchmark']],
            index=pd.DatetimeIndex([t for t, _ in row['benchmark']]).tz_convert('Asia/Kolkata'))
    return RunRecord(fills, equity, prices, row['start_cash'])


def _print_verdicts(verdicts):
    for verdict in verdicts:
        print(verdict.verdict)
        for check in verdict.checks:
            bar = check.evidence.get('first_bad_bar')
            detail = f' at bar {bar}' if bar is not None else ''
            reason = check.evidence.get('reason')
            if reason:
                detail += f': {reason}'
            print(f'{check.name}: {check.verdict}{detail}')
    return int(any(check.verdict == 'FAIL' for verdict in verdicts for check in verdict.checks))


def _holdout():
    state = _state()
    if 'lock_path' not in state:
        raise SetupError('Missing lock. Run autopsy lock create first.')
    lock = Lock.open(state['lock_path'])
    if lock.openings > 1 and state.get('evaluation_path'):
        verdicts, _ = _evaluation(state)
        return _print_verdicts(verdicts)
    prices, _ = load_snapshot(state['locked_snapshot'])
    verdicts, records = [], []
    for item in lock._header['picks']:
        pick = Pick(**item)
        strategy = REGISTRY[pick.strategy]
        signals = strategy.signals(prices, strategy.features(prices, pick.params), pick.params)
        record = run_backtest(prices, signals, pick.mode, slippage_bps=2 * pick.base_slippage_bps,
                              rates=load_rates('zerodha'))
        if state.get('locked_benchmark'):
            benchmark, _ = load_snapshot(state['locked_benchmark'])
            benchmark = benchmark.loc[(benchmark.index >= lock.locked_start) & (benchmark.index < lock.locked_end)]
            if not benchmark.empty:
                # Normalized buy-and-hold context, explicitly before ETF costs.
                record.reported_equity.attrs['nifty_etf_equity'] = record.start_cash * benchmark.close / benchmark.open.iloc[0]
        verdict = decide(pick, record, [], lock)
        verdict.stats.update(title=f'{pick.strategy.replace("_", " ").capitalize()} / {pick.mode}', mode=pick.mode,
            notes=[state['locked_source'], 'Verdict uses the locked final 12 months only, at doubled slippage and before tax.',
                   'Universe membership history is unavailable; a fixed stock list can have survivorship bias.',
                   'Observed-session coverage cannot detect days absent from every symbol. Few market regimes are represented.'])
        verdicts.append(verdict)
        records.append(record)
    path = data_dir() / 'evaluations' / (uuid4().hex + '.json')
    _write(path, {'verdicts': [asdict(v) for v in verdicts], 'records': [_encode_record(r) for r in records],
                  'lock_path': state['lock_path'], 'locked_snapshot': state['locked_snapshot']})
    state['evaluation_path'] = str(path)
    state['evaluation_digest'] = _digest(json.loads(path.read_text()))
    _save(state)
    return _print_verdicts(verdicts)


def _evaluation(state):
    if 'evaluation_path' not in state:
        if state.get('preview_path'):
            payload = json.loads(Path(state['preview_path']).read_text())
            prices, _ = load_snapshot(payload['snapshot'])
            return ([Verdict(row['verdict'], row['reasons'], [CheckResult(**c) for c in row['checks']], row['stats'])
                     for row in payload['verdicts']], [_decode_record(row, prices) for row in payload['records']])
        raise SetupError('Missing holdout evaluation. Run autopsy holdout open first.')
    payload = json.loads(Path(state['evaluation_path']).read_text())
    if _digest(payload) != state['evaluation_digest']:
        raise SetupError('Saved evaluation integrity mismatch.')
    prices, _ = load_snapshot(payload['locked_snapshot'])
    records = [_decode_record(row, prices) for row in payload['records']]
    verdicts = [Verdict(row['verdict'], row['reasons'], [CheckResult(**c) for c in row['checks']], row['stats'])
                for row in payload['verdicts']]
    # Cached reports do not reopen the holdout, but always recheck its journal.
    reason = None
    try:
        lock = _read_lock(payload['lock_path'])
        valid = lock.verify() and all(lock.matches(Pick(**pick), record.prices)
                                     for pick, record in zip(lock._header['picks'], records))
        if lock.openings != 1 or not valid:
            reason = f'holdout opened {lock.openings} times' if lock.openings != 1 else 'lock integrity mismatch'
    except (OSError, ValueError, KeyError):
        reason = 'lock integrity mismatch'
    if reason:
        for verdict in verdicts:
            verdict.verdict = 'NO-GO'
            verdict.reasons = list(dict.fromkeys([*verdict.reasons, reason]))
            verdict.checks = [c for c in verdict.checks if c.name != 'lock'] + [CheckResult('lock', 'FAIL', {'reason': reason})]
    return verdicts, records


def _oracle(args):
    try:
        from cases.oracle.run_case import run_oracle_case
        case = run_oracle_case()
    except ModuleNotFoundError as exc:
        raise SetupError('Oracle case requires this repository and the oracle extra (gymnasium).') from exc
    checks = [case['ledger'], case['lookahead'], CheckResult('drawdown', 'FAIL', {
        'probe': [100, 90, 80], 'oracle_drawdown': case['oracle_drawdown'], 'true_drawdown': case['true_drawdown']})]
    verdict = Verdict('NO-GO', ['The reported account creates money on a flat market.',
                              'Future volatility enters the observations.',
                              'The drawdown calculation drops the first observation.'], checks,
                      {'title': 'Oracle case / A flat market, invented money', 'mode': 'intraday', 'dsr': None,
                       'notes': ['Synthetic flat price of ₹100. Four scripted round trips. Zero fees and slippage isolate the accounting bug.',
                                 'Drawdown probe: 100 → 90 → 80. Oracle: −11.11%; reference: −20.00%.',
                                 'This is a bug demonstration, not a selected strategy or a locked research result.']})
    if args.report:
        print(render_report([verdict], [case['record']], [], args.report, slab_rate=args.slab_rate))
    return _print_verdicts([verdict])


def _parser():
    parser = argparse.ArgumentParser(prog='autopsy', description='Local historical research. Never places orders.')
    commands = parser.add_subparsers(dest='command', required=True)
    case = commands.add_parser('case').add_subparsers(dest='case_command', required=True)
    oracle = case.add_parser('oracle')
    oracle.add_argument('--report', metavar='FILE')
    oracle.add_argument('--slab-rate', type=float, default=30)
    data = commands.add_parser('data').add_subparsers(dest='data_command', required=True)
    synthetic = data.add_parser('synthetic', help='seeded random walk with invented short sessions')
    synthetic.add_argument('--days', type=int, default=520)
    synthetic.add_argument('--seed', type=int, default=17)
    nse = data.add_parser('import-nse')
    nse.add_argument('csv', nargs='+')
    fetch = data.add_parser('fetch-upstox')
    fetch.add_argument('--symbols', required=True, help='text file: one instrument key per line')
    fetch.add_argument('--from', dest='start', required=True)
    fetch.add_argument('--to', dest='end', default=(pd.Timestamp.now(tz='Asia/Kolkata') - pd.Timedelta(days=1)).date().isoformat())
    fetch.add_argument('--unit', default='minutes')
    fetch.add_argument('--interval', type=int, default=5)
    fetch.add_argument('--token-path', default=DEFAULT_TOKEN_PATH)
    events = commands.add_parser('events').add_subparsers(dest='events_command', required=True).add_parser('import')
    events.add_argument('csv', nargs='+')
    events.add_argument('--kind', choices=['announcements', 'bulk_deal', 'block_deal'], default='announcements')
    research = commands.add_parser('research').add_subparsers(dest='research_command', required=True).add_parser('run')
    research.add_argument('--mode', choices=['intraday', 'swing'], required=True)
    research.add_argument('--benchmark-symbol', help='identify the Nifty 50 ETF symbol in imported data; excludes it from strategy trades')
    commands.add_parser('lock').add_subparsers(dest='lock_command', required=True).add_parser('create')
    commands.add_parser('holdout').add_subparsers(dest='holdout_command', required=True).add_parser('open')
    report = commands.add_parser('report')
    report.add_argument('--out', required=True)
    report.add_argument('--slab-rate', type=float, default=30)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == 'data':
            return _data(args)
        if args.command == 'events':
            return _events(args)
        if args.command == 'research':
            return _research(args)
        if args.command == 'lock':
            return _create_lock()
        if args.command == 'holdout':
            return _holdout()
        if args.command == 'case':
            return _oracle(args)
        verdicts, records = _evaluation(_state())
        log = TrialLog()
        if not log.verify():
            for verdict in verdicts:
                verdict.verdict = 'NO-GO'
                verdict.checks.append(CheckResult('trial_log', 'FAIL', {'reason': 'Trial log integrity mismatch'}))
                verdict.stats.setdefault('notes', []).append('Lifetime trial history is unavailable because its integrity check failed.')
            log = None
        print(render_report(verdicts, records, log, args.out, slab_rate=args.slab_rate))
        return _print_verdicts(verdicts)
    except (TokenMissing, UpstoxError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except SetupError as exc:
        print(f'Setup error: {exc}', file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        # Preserve Task 9's sanitized errors; never expose API response data,
        # arbitrary input-file contents or a traceback through the CLI.
        print('Setup error: check input files, dates, interval and private data directory; missing or invalid data/state.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
