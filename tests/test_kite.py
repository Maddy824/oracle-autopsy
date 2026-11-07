"""Invented Kite fixtures only. Every HTTP request uses MockTransport."""

import gzip
import hashlib
import json
import logging
from pathlib import Path
import stat
import traceback
from urllib.parse import parse_qs, urlsplit

import httpx
import pandas as pd
import pytest

from autopsy.cli import main
from autopsy.data.corporate import with_actions
from autopsy.data.kite import (KiteClient, KiteCredentialsMissing, KiteError, KiteSessionMissing,
                               create_session, login_url, parse_request_token)
from autopsy.data.store import load_snapshot


NOW = pd.Timestamp('2026-11-05 12:00', tz='Asia/Kolkata')
API_KEY, SECRET, ACCESS, REQUEST = 'InventedKey', 'InventedSecret', 'InventedAccess', 'InventedRequest'
CSV = ('instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,'
       'lot_size,instrument_type,segment,exchange\n'
       '101,1,RELIANCE,Invented equity,0,,0,0.05,1,EQ,NSE,NSE\n'
       '202,2,NIFTY 50,Invented index,0,,0,0.05,1,EQ,INDICES,NSE\n').encode()


class Clock:
    def __init__(self):
        self.time = 0.
        self.waits = []

    def __call__(self):
        return self.time

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.time += seconds


def private_json(path, value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


@pytest.fixture
def files(tmp_path):
    credentials = private_json(tmp_path / 'credentials.json', {'api_key': API_KEY, 'api_secret': SECRET})
    session = private_json(tmp_path / 'session.json', {'access_token': ACCESS,
                           'login_time': NOW.isoformat(), 'expires_at': '2026-11-06T06:00:00+05:30'})
    return credentials, session


def payload(time='2025-01-01T09:15:00+0530'):
    return {'status': 'success', 'data': {'candles': [[time, 100, 102, 99, 101, 20]]}}


def client_for(files, handle=None, **kwargs):
    clock = kwargs.pop('clock', Clock())
    def default(request):
        if request.url.path == '/instruments/NSE':
            return httpx.Response(200, content=CSV)
        return httpx.Response(200, json=payload())
    return KiteClient(*files, transport=httpx.MockTransport(handle or default), now=kwargs.pop('now', NOW),
                      clock=clock, sleep=clock.sleep, cache=kwargs.pop('cache', False), **kwargs)


def fetch(client, **kwargs):
    return client.candles(kwargs.get('symbol', 'NSE:RELIANCE'), kwargs.get('interval', '5minute'),
                          kwargs.get('start', '2025-01-01'), kwargs.get('end', '2025-01-01'))


def test_login_url():
    assert login_url(API_KEY) == 'https://kite.zerodha.com/connect/login?v=3&api_key=InventedKey'
    assert login_url('key+value').endswith('api_key=key%2Bvalue')


@pytest.mark.parametrize('state', ['InventedNonce_-', 'nonce+with &reserved=chars', ''])
def test_login_url_state_redirect_params(state):
    query = parse_qs(urlsplit(login_url(API_KEY, state=state)).query)
    assert query['api_key'] == [API_KEY]
    assert query['v'] == ['3']
    assert parse_qs(query['redirect_params'][0], keep_blank_values=True) == {'state': [state]}
    assert 'redirect_params=state%3D' in login_url(API_KEY, state=state)


@pytest.mark.parametrize('text', [REQUEST, '  ' + REQUEST + '\n',
    'http://127.0.0.1/?request_token=' + REQUEST + '&action=login&status=success',
    'http://127.0.0.1/?request_token=' + REQUEST])
def test_parse_token(text):
    assert parse_request_token(text) == REQUEST


@pytest.mark.parametrize('text', ['', 'junk!?', 'a_b', 'a b', 'é',
    'http://127.0.0.1/?request_token=Secret&status=error',
    'http://127.0.0.1/?request_token=Secret&status=',
    'http://127.0.0.1/?request_token=A&request_token=B',
    'http://127.0.0.1/?status=success', 'http://127.0.0.1/?request_token=a%2Fb'])
def test_parse_token_rejects_without_echo(text):
    with pytest.raises(ValueError) as exc:
        parse_request_token(text)
    assert 'Secret' not in str(exc.value)


@pytest.mark.parametrize('login,expires', [
    ('2026-11-05 05:59:59', '2026-11-05T06:00:00+05:30'),
    ('2026-11-05 06:00:00', '2026-11-06T06:00:00+05:30'),
    ('2026-11-05 12:00:00', '2026-11-06T06:00:00+05:30'),
    ('2026-11-04T23:30:00Z', '2026-11-05T06:00:00+05:30')])
def test_exchange_checksum_expiry_and_private_atomic_write(files, tmp_path, monkeypatch, login, expires):
    import autopsy.data.kite as kite
    calls, modes = [], []
    original_open = kite.os.open
    def observe_open(path, flags, mode):
        fd = original_open(path, flags, mode)
        modes.append(stat.S_IMODE(Path(path).stat().st_mode))
        assert flags & kite.os.O_EXCL and mode == 0o600
        return fd
    monkeypatch.setattr(kite.os, 'open', observe_open)
    def handle(request):
        calls.append(request)
        assert request.method == 'POST'
        assert request.url == 'https://api.kite.trade/session/token'
        assert request.headers['X-Kite-Version'] == '3'
        assert 'Authorization' not in request.headers
        assert request.headers['Content-Type'] == 'application/x-www-form-urlencoded'
        assert parse_qs(request.content.decode()) == {
            'api_key': [API_KEY], 'request_token': [REQUEST],
            'checksum': [hashlib.sha256((API_KEY + REQUEST + SECRET).encode()).hexdigest()]}
        return httpx.Response(200, json={'status': 'success', 'data': {
            'access_token': ACCESS, 'login_time': login, 'irrelevant': SECRET}})
    path = tmp_path / 'new-directory' / 'session.json'
    now = pd.Timestamp(login)
    now = now.tz_localize('Asia/Kolkata') if now.tz is None else now
    session = create_session(files[0], path, REQUEST, transport=httpx.MockTransport(handle), now=now)
    assert len(calls) == 1
    assert session['expires_at'] == expires
    assert set(session) == {'access_token', 'login_time', 'expires_at'}
    assert json.loads(path.read_text()) == session
    assert modes == [0o600]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize('which,error', [(0, KiteCredentialsMissing), (1, KiteSessionMissing)])
@pytest.mark.parametrize('problem', ['missing', 'insecure', 'invalid'])
def test_missing_files(files, which, error, problem):
    path = files[which]
    if problem == 'missing':
        path.unlink()
    elif problem == 'insecure':
        path.chmod(0o644)
    else:
        path.write_text('not json ' + SECRET)
    with pytest.raises(error, match='autopsy kite login'):
        client_for(files)


@pytest.mark.parametrize('now', ['2026-11-06T06:00:00+05:30', '2026-11-07T06:00:00+05:30'])
def test_expired_session(files, now):
    with pytest.raises(KiteSessionMissing, match='autopsy kite login'):
        client_for(files, now=now)


@pytest.mark.parametrize('status', [200, 400, 403])
def test_token_exception(files, status):
    def handle(request):
        return httpx.Response(status, json={'status': 'error', 'error_type': 'TokenException', 'message': SECRET})
    with pytest.raises(KiteSessionMissing, match='autopsy kite login') as exc:
        client_for(files, handle).instruments()
    assert SECRET not in str(exc.value)


@pytest.mark.parametrize('failure', [403, 500, 429, 'json', 'transport', 'api'])
def test_failure_sanitisation(files, failure, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    body = 'RESPONSE BODY ' + SECRET + ACCESS + REQUEST
    def handle(request):
        if failure == 'transport':
            raise httpx.ReadError(body, request=request)
        if failure == 'api':
            return httpx.Response(200, json={'status': 'error', 'error_type': body, 'message': body})
        return httpx.Response(200 if failure == 'json' else failure, text=body)
    client = client_for(files, handle)
    with pytest.raises(KiteError) as exc:
        client._request('/instruments/historical/101/minute')
    rendered = ''.join(traceback.format_exception(exc.type, exc.value, exc.tb))
    captured = capsys.readouterr()
    output = str(exc.value) + rendered + captured.out + captured.err + caplog.text + repr(client)
    for secret in [SECRET, ACCESS, REQUEST, 'RESPONSE BODY']:
        assert secret not in output


def test_429_backoff_and_headers(files):
    clock, times = Clock(), []
    def handle(request):
        times.append(clock())
        assert request.headers['X-Kite-Version'] == '3'
        assert request.headers['Authorization'] == f'token {API_KEY}:{ACCESS}'
        assert SECRET not in str(request.url) and ACCESS not in str(request.url)
        return httpx.Response(429) if len(times) < 4 else httpx.Response(200, json=payload())
    result = client_for(files, handle, clock=clock)._request('/instruments/historical/101/minute')
    assert result == payload()
    assert clock.waits == [1., 2., 4.]
    assert times == [0., 1., 3., 7.]


@pytest.mark.parametrize('interval,days', [('minute', 59), ('5minute', 99), ('day', 1999),
    ('3minute', 99), ('10minute', 99), ('15minute', 199), ('30minute', 199), ('60minute', 399)])
def test_chunk_bounds_and_spacing(files, interval, days):
    requests, times, clock = [], [], Clock()
    first = pd.Timestamp('2017-01-01', tz='Asia/Kolkata')
    end = first + pd.Timedelta(days=days * 2)
    def handle(request):
        times.append(clock())
        assert request.method == 'GET'
        assert request.headers['X-Kite-Version'] == '3'
        assert request.headers['Authorization'] == f'token {API_KEY}:{ACCESS}'
        if request.url.path == '/instruments/NSE':
            return httpx.Response(200, content=CSV)
        requests.append(request)
        assert request.url.path == f'/instruments/historical/101/{interval}'
        assert request.url.params['continuous'] == request.url.params['oi'] == '0'
        return httpx.Response(200, json=payload(request.url.params['from'].replace(' ', 'T') + '+0530'))
    result = fetch(client_for(files, handle, clock=clock), interval=interval,
                   start=first.date(), end=end.date().isoformat())
    assert len(requests) == 3
    expected_bounds = [(first, first + pd.Timedelta(days=days) - pd.Timedelta(seconds=1)),
                       (first + pd.Timedelta(days=days), end - pd.Timedelta(seconds=1)),
                       (end, end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))]
    assert [(r.url.params['from'], r.url.params['to']) for r in requests] == [
        (lo.strftime('%Y-%m-%d %H:%M:%S'), hi.strftime('%Y-%m-%d %H:%M:%S')) for lo, hi in expected_bounds]
    assert all(b - a >= .35 - 1e-12 for a, b in zip(times, times[1:]))
    assert len(result) == 3 and result.attrs['price_basis'] == 'adjusted'
    assert str(result.index.tz) == 'Asia/Kolkata'
    assert result.symbol.unique().tolist() == ['NSE:RELIANCE']


def test_aware_bounds_preserved(files):
    seen = []
    def handle(request):
        if request.url.path == '/instruments/NSE':
            return httpx.Response(200, content=CSV)
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=payload())
    fetch(client_for(files, handle), start=pd.Timestamp('2025-01-01T03:45:00Z'),
          end=pd.Timestamp('2025-01-01T09:20:00+0530'))
    assert seen[0]['from'] == '2025-01-01 09:15:00'
    assert seen[0]['to'] == '2025-01-01 09:20:00'


@pytest.mark.parametrize('kwargs', [{'interval': '2minute'}, {'start': '2025-01-02'},
    {'start': pd.Timestamp('2025-01-01 09:15')}, {'symbol': 'RELIANCE'}])
def test_bad_arguments_before_http(files, kwargs):
    def handle(request):
        pytest.fail('invalid arguments should not make requests')
    with pytest.raises(ValueError):
        fetch(client_for(files, handle), **kwargs)


@pytest.mark.parametrize('rows', [None, [[]], [['2025-01-01T09:15:00', 100, 102, 99, 101, 20]],
    [['bad timestamp', 100, 102, 99, 101, 20]],
    [['2025-01-02T09:15:00+0530', 100, 102, 99, 101, 20]],
    [['2025-01-01T09:15:00+0530', 100, 102, 99, 101]],
    [['2025-01-01T09:15:00+0530', 100, 102, 99, 101, 20, 0, 0]],
    [['2025-01-01T09:15:00+0530', 100, 98, 99, 101, 20]],
    [['2025-01-01T09:15:00+0530', 100, 102, 99, 101, -1]],
    [['2025-01-01T09:15:00+0530', 'SECRET', 102, 99, 101, 20]],
    payload()['data']['candles'] * 2])
def test_malformed_candles(files, rows):
    def handle(request):
        if request.url.path == '/instruments/NSE':
            return httpx.Response(200, content=CSV)
        return httpx.Response(200, json={'status': 'success', 'data': {'candles': rows}})
    with pytest.raises(KiteError, match='Invalid Kite'):
        fetch(client_for(files, handle))


@pytest.mark.parametrize('rows', [[], [payload()['data']['candles'][0] + [123]]])
def test_empty_and_seven_value_candles(files, rows):
    def handle(request):
        if request.url.path == '/instruments/NSE':
            return httpx.Response(200, content=CSV)
        return httpx.Response(200, json={'status': 'success', 'data': {'candles': rows}})
    frame = fetch(client_for(files, handle))
    assert len(frame) == len(rows)
    assert frame.attrs['price_basis'] == 'adjusted'


@pytest.mark.parametrize('compressed', [False, True])
def test_instruments_resolve_and_cache(files, tmp_path, compressed):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=gzip.compress(CSV) if compressed else CSV)
    client = client_for(files, handle, cache=True, cache_dir=tmp_path / 'cache')
    assert client.resolve('NSE:RELIANCE') == 101
    assert client.resolve('NSE:NIFTY 50') == 202
    with pytest.raises(ValueError, match='Unknown'):
        client.resolve('NSE:UNKNOWN')
    assert len(calls) == 1
    frame = client.instruments()
    assert frame.loc[frame.tradingsymbol == 'NIFTY 50', 'segment'].iloc[0] == 'INDICES'
    assert (tmp_path / 'cache/instruments-NSE-2026-11-05.csv').read_bytes() == CSV


def test_ambiguous_symbol(files):
    repeated = CSV + CSV.splitlines(keepends=True)[1]
    client = client_for(files, lambda _: httpx.Response(200, content=repeated))
    with pytest.raises(ValueError, match='Ambiguous'):
        client.resolve('NSE:RELIANCE')


def test_candle_cache_reuse_verified_and_adjusted(files, tmp_path):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=CSV) if request.url.path == '/instruments/NSE' else httpx.Response(200, json=payload())
    client = client_for(files, handle, cache=True, cache_dir=tmp_path / 'cache')
    first = fetch(client)
    pd.testing.assert_frame_equal(first, fetch(client))
    assert first.attrs == fetch(client).attrs
    assert len(calls) == 2  # One instruments request and one historical request, ever.
    path, = (tmp_path / 'cache').glob('*.parquet')
    restored, meta = load_snapshot(path)
    assert meta['kind'] == restored.attrs['price_basis'] == 'adjusted'
    for secret in [SECRET, ACCESS, REQUEST, API_KEY]:
        assert secret not in path.name + json.dumps(meta)
    with pytest.raises(ValueError, match='raw, not adjusted'):
        with_actions(restored, pd.DataFrame())
    path.write_bytes(path.read_bytes() + b'tampered')
    with pytest.raises(ValueError, match='hash mismatch'):
        fetch(client)
    assert len(calls) == 2


def test_instruments_rollover_uses_date_not_saved_token(files, tmp_path):
    now = [pd.Timestamp('2026-11-05 23:59:59', tz='Asia/Kolkata')]
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=CSV if len(calls) == 1 else CSV.replace(b'101,1', b'303,1'))
    client = client_for(files, handle, now=lambda: now[0], cache=True, cache_dir=tmp_path / 'cache')
    assert client.resolve('NSE:RELIANCE') == 101
    now[0] += pd.Timedelta(seconds=1)
    assert client.resolve('NSE:RELIANCE') == 303
    assert len(calls) == 2


def test_fetch_cli_adjusted_snapshot_and_yesterday_cap(files, tmp_path, monkeypatch, capsys):
    requests = []
    def handle(request):
        requests.append(request)
        if request.url.path == '/instruments/NSE':
            return httpx.Response(200, content=CSV)
        return httpx.Response(200, json=payload())
    client = client_for(files, handle, cache=True, cache_dir=tmp_path / 'cache')
    monkeypatch.setattr('autopsy.cli.KiteClient', lambda **kwargs: client)
    monkeypatch.setenv('AUTOPSY_DATA_DIR', str(tmp_path / 'data'))
    symbols = tmp_path / 'symbols.txt'
    symbols.write_text('# invented symbols\nNSE:RELIANCE # equity\n\nNSE:NIFTY 50\n')
    assert main(['data', 'fetch-kite', '--symbols', str(symbols), '--from', '2025-01-01',
                 '--to', '2099-01-01', '--interval', 'day']) == 0
    yesterday = (pd.Timestamp.now(tz='Asia/Kolkata') - pd.Timedelta(days=1)).date().isoformat()
    assert [r.url.params['to'][:10] for r in requests if 'historical' in r.url.path] == [yesterday] * 2
    state = json.loads((tmp_path / 'data/session.json').read_text())
    prices, meta = load_snapshot(state['prices_path'])
    assert meta['kind'] == prices.attrs['price_basis'] == 'adjusted'
    assert Path(state['prices_path']).parent.name == 'adjusted'
    assert meta['source'] == 'Zerodha Kite Connect historical candles'
    assert set(prices.symbol) == {'NSE:RELIANCE', 'NSE:NIFTY 50'}
    assert len(json.loads(prices.attrs['expected_bars'])) == 2
    with pytest.raises(ValueError, match='raw, not adjusted'):
        with_actions(prices, pd.DataFrame())
    assert ACCESS not in capsys.readouterr().out


@pytest.mark.parametrize('no_browser', [False, True])
def test_login_cli(files, tmp_path, monkeypatch, capsys, no_browser):
    opened = []
    monkeypatch.setattr('autopsy.cli.webbrowser.open', opened.append)
    monkeypatch.setattr('builtins.input', lambda _: 'http://127.0.0.1/?request_token=' + REQUEST + '&status=success')
    def exchange(credentials, session, token):
        return create_session(credentials, session, token, now=NOW, transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={'status': 'success', 'data': {
                'access_token': ACCESS, 'login_time': NOW.isoformat()}})))
    monkeypatch.setattr('autopsy.cli.create_session', exchange)
    session = tmp_path / 'new-session.json'
    args = ['kite', 'login', '--paste', '--credentials', str(files[0]), '--session', str(session)]
    assert main(args + (['--no-browser'] if no_browser else [])) == 0
    assert opened == ([] if no_browser else [login_url(API_KEY)])
    out = capsys.readouterr().out
    assert login_url(API_KEY) in out and 'error page at 127.0.0.1' in out
    assert 'Kite session saved; valid until 2026-11-06 06:00:00 IST' in out
    assert all(secret not in out for secret in [SECRET, ACCESS, REQUEST])
    assert stat.S_IMODE(session.stat().st_mode) == 0o600


@pytest.mark.parametrize('command', ['login', 'fetch'])
def test_missing_credentials_cli(tmp_path, capsys, command):
    args = ['kite', 'login', '--no-browser'] if command == 'login' else [
        'data', 'fetch-kite', '--symbols', str(tmp_path / 'missing-symbols'), '--from', '2025-01-01']
    assert main(args + ['--credentials', str(tmp_path / 'missing'), '--session', str(tmp_path / 'missing-session')]) == 2
    out = capsys.readouterr().err
    assert 'autopsy kite login' in out and 'mode 600' in out and 'Traceback' not in out


def test_failed_exchange_cli(files, monkeypatch, capsys):
    monkeypatch.setattr('builtins.input', lambda _: REQUEST)
    def exchange(credentials, session, token):
        return create_session(credentials, session, token, now=NOW, transport=httpx.MockTransport(
            lambda _: httpx.Response(403, text=SECRET + ACCESS + REQUEST)))
    monkeypatch.setattr('autopsy.cli.create_session', exchange)
    old = files[1].read_bytes()
    assert main(['kite', 'login', '--paste', '--credentials', str(files[0]), '--session', str(files[1]), '--no-browser']) == 2
    captured = capsys.readouterr()
    assert 'autopsy kite login' in captured.err and 'Traceback' not in captured.err
    assert all(secret not in captured.out + captured.err for secret in [SECRET, ACCESS, REQUEST])
    assert files[1].read_bytes() == old


@pytest.mark.parametrize('pasted', ['', 'http://127.0.0.1/?status=error&request_token=abc'])
def test_login_cli_bad_paste_says_what_to_paste(files, monkeypatch, capsys, pasted):
    monkeypatch.setattr('builtins.input', lambda _: pasted)
    monkeypatch.setattr('autopsy.cli.create_session', lambda *a: pytest.fail('no exchange on bad paste'))
    assert main(['kite', 'login', '--paste', '--credentials', str(files[0]), '--session', str(files[1]), '--no-browser']) == 2
    err = capsys.readouterr().err
    assert 'paste the successful redirect URL' in err and 'Traceback' not in err


def test_fetch_cli_names_unknown_symbol_before_downloading(files, tmp_path, monkeypatch, capsys):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=CSV) if request.url.path == '/instruments/NSE' else httpx.Response(200, json=payload())
    client = client_for(files, handle, cache=False)
    monkeypatch.setattr('autopsy.cli.KiteClient', lambda **kwargs: client)
    monkeypatch.setenv('AUTOPSY_DATA_DIR', str(tmp_path / 'data'))
    symbols = tmp_path / 'symbols.txt'
    symbols.write_text('NSE:RELIANCE\nNSE:NOSUCHSTOCK\n')
    assert main(['data', 'fetch-kite', '--symbols', str(symbols), '--from', '2025-01-01', '--interval', 'day']) == 2
    err = capsys.readouterr().err
    assert "'NSE:NOSUCHSTOCK'" in err and 'Traceback' not in err
    assert not any('historical' in r.url.path for r in requests)
    symbols.write_text('# only comments\n\n')
    assert main(['data', 'fetch-kite', '--symbols', str(symbols), '--from', '2025-01-01']) == 2
    assert 'lists no symbols' in capsys.readouterr().err


def test_expired_fetch_cli(files, tmp_path, monkeypatch, capsys):
    client = client_for(files, lambda _: httpx.Response(403))
    monkeypatch.setattr('autopsy.cli.KiteClient', lambda **_: client)
    symbols = tmp_path / 'symbols.txt'
    symbols.write_text('NSE:RELIANCE\n')
    assert main(['data', 'fetch-kite', '--symbols', str(symbols), '--from', '2025-01-01']) == 2
    captured = capsys.readouterr()
    assert 'autopsy kite login' in captured.err and 'Traceback' not in captured.err


def test_missing_cache_sidecar_is_repaired(files, tmp_path):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=CSV) if request.url.path == '/instruments/NSE' else httpx.Response(200, json=payload())
    client = client_for(files, handle, cache=True, cache_dir=tmp_path / 'cache')
    fetch(client)
    path, = (tmp_path / 'cache').glob('*.parquet')
    path.with_suffix('.json').unlink()
    fetch(client)
    load_snapshot(path)
    fetch(client)
    assert len(calls) == 3


def test_session_exchange_transport_failure_never_leaks(files, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    def handle(request):
        raise httpx.ReadError(SECRET + ACCESS + REQUEST, request=request)
    before = files[1].read_bytes()
    with pytest.raises(KiteError) as exc:
        create_session(*files, REQUEST, transport=httpx.MockTransport(handle), now=NOW)
    rendered = ''.join(traceback.format_exception(exc.type, exc.value, exc.tb))
    captured = capsys.readouterr()
    output = rendered + caplog.text + captured.out + captured.err
    assert all(secret not in output for secret in [SECRET, ACCESS, REQUEST])
    assert files[1].read_bytes() == before


def test_reused_instrument_token_refetches_old_symbol_cache(files, tmp_path):
    # Tomorrow's dump can assign today's token to a different trading symbol.
    now = [pd.Timestamp('2026-11-05 23:59:59', tz='Asia/Kolkata')]
    calls = []
    def handle(request):
        calls.append(request)
        if request.url.path == '/instruments/NSE':
            csv = CSV if now[0].day == 5 else CSV.replace(b'RELIANCE', b'NEWNAME')
            return httpx.Response(200, content=csv)
        data = payload()
        data['data']['candles'][0][5] = now[0].day
        return httpx.Response(200, json=data)
    client = client_for(files, handle, now=lambda: now[0], cache=True, cache_dir=tmp_path / 'cache')
    assert fetch(client).volume.tolist() == [5.]
    now[0] += pd.Timedelta(seconds=1)
    result = fetch(client, symbol='NSE:NEWNAME')
    assert result.symbol.tolist() == ['NSE:NEWNAME'] and result.volume.tolist() == [6.]
    pd.testing.assert_frame_equal(result, fetch(client, symbol='NSE:NEWNAME'))
    assert len(calls) == 4
    assert len(list((tmp_path / 'cache').glob('*.parquet'))) == 1


def _daily(rows):
    def handle(request):
        if request.url.path == '/instruments/NSE':
            return httpx.Response(200, content=CSV)
        return httpx.Response(200, json={'status': 'success', 'data': {'candles': rows}})
    return handle


def test_daily_candles_stamped_0915_become_dates_and_identical_repeats_collapse(files):
    # Invented rows modelled on Kite's 2015/16 switch from 00:00 to 09:15 stamps.
    rows = [['2025-01-01T00:00:00+0530', 100, 102, 99, 101, 20],
            ['2025-01-01T09:15:00+0530', 100, 102, 99, 101, 20],
            ['2025-01-02T09:15:00+0530', 101, 103, 100, 102, 30]]
    prices = fetch(client_for(files, _daily(rows)), interval='day', start='2025-01-01', end='2025-01-02')
    assert list(prices.index) == [pd.Timestamp('2025-01-01', tz='Asia/Kolkata'),
                                  pd.Timestamp('2025-01-02', tz='Asia/Kolkata')]
    assert prices.close.tolist() == [101, 102]


def test_conflicting_daily_bars_on_one_date_are_rejected(files):
    rows = [['2025-01-01T00:00:00+0530', 100, 102, 99, 101, 20],
            ['2025-01-01T09:15:00+0530', 100, 102, 99, 105, 20]]
    with pytest.raises(KiteError, match='conflicting daily bars'):
        fetch(client_for(files, _daily(rows)), interval='day', start='2025-01-01', end='2025-01-01')


def test_all_zero_price_rows_are_dropped_but_partial_zeros_fail(files):
    rows = [['2025-01-01T00:00:00+0530', 0, 0, 0, 0, 7000],
            ['2025-01-02T00:00:00+0530', 101, 103, 100, 102, 30]]
    prices = fetch(client_for(files, _daily(rows)), interval='day', start='2025-01-01', end='2025-01-02')
    assert prices.close.tolist() == [102]
    bad = [['2025-01-02T00:00:00+0530', 101, 103, 100, 0, 30]]
    with pytest.raises(KiteError):
        fetch(client_for(files, _daily(bad)), interval='day', start='2025-01-02', end='2025-01-02')


def test_fetch_kite_names_bad_symbol_or_skips_it(files, tmp_path, monkeypatch, capsys):
    import autopsy.cli as cli
    from autopsy.data.kite import KiteClient as Real
    original = Real.candles
    monkeypatch.setenv('AUTOPSY_DATA_DIR', str(tmp_path / 'data'))
    symbols = tmp_path / 'symbols.txt'
    symbols.write_text('NSE:RELIANCE\nNSE:NIFTY 50\n')

    def candles(self, symbol, *args):
        if symbol == 'NSE:NIFTY 50':
            raise KiteError('Invalid Kite candles; conflicting daily bars on one date')
        return original(self, symbol, *args)

    monkeypatch.setattr(cli, 'KiteClient', lambda **kw: client_for(files))
    monkeypatch.setattr(Real, 'candles', candles)
    base = ['data', 'fetch-kite', '--symbols', str(symbols), '--from', '2025-01-01', '--to', '2025-01-01']
    assert cli.main(base) == 2
    assert '(NSE:NIFTY 50)' in capsys.readouterr().err
    assert cli.main(base + ['--skip-invalid']) == 0
    assert 'Skipped 1 symbol(s) with invalid Kite data: NSE:NIFTY 50' in capsys.readouterr().out


def test_fetch_kite_retries_network_errors_then_stops_never_skips(files, tmp_path, monkeypatch, capsys):
    import autopsy.cli as cli
    from autopsy.data.kite import KiteClient as Real, KiteTransportError
    original = Real.candles
    monkeypatch.setenv('AUTOPSY_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(cli.time_module, 'sleep', lambda seconds: None)
    symbols = tmp_path / 'symbols.txt'
    symbols.write_text('NSE:RELIANCE\n')
    calls = []

    def flaky(self, symbol, *args):
        calls.append(symbol)
        if len(calls) < 3:
            raise KiteTransportError('Kite transport or response failure')
        return original(self, symbol, *args)

    monkeypatch.setattr(cli, 'KiteClient', lambda **kw: client_for(files))
    monkeypatch.setattr(Real, 'candles', flaky)
    base = ['data', 'fetch-kite', '--symbols', str(symbols), '--from', '2025-01-01', '--to', '2025-01-01', '--skip-invalid']
    assert cli.main(base) == 0 and len(calls) == 3

    def down(self, symbol, *args):
        raise KiteTransportError('Kite transport or response failure')

    monkeypatch.setattr(Real, 'candles', down)
    assert cli.main(base) == 2
    assert 'rerun the same command to resume' in capsys.readouterr().err


def test_fetch_kite_skips_symbols_missing_from_instruments(files, tmp_path, monkeypatch, capsys):
    import autopsy.cli as cli
    monkeypatch.setenv('AUTOPSY_DATA_DIR', str(tmp_path / 'data'))
    symbols = tmp_path / 'symbols.txt'
    symbols.write_text('NSE:RELIANCE\nNSE:GONE\n')
    monkeypatch.setattr(cli, 'KiteClient', lambda **kw: client_for(files))
    base = ['data', 'fetch-kite', '--symbols', str(symbols), '--from', '2025-01-01', '--to', '2025-01-01']
    assert cli.main(base) == 2
    assert cli.main(base + ['--skip-invalid']) == 0
    assert "Skipped 1 symbol(s) not in today's Kite instrument list: NSE:GONE" in capsys.readouterr().out
