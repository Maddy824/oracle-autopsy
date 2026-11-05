"""Invented sessions, loopback HTTP and MockTransport only; no broker access."""

from concurrent.futures import ThreadPoolExecutor
import errno
import http.client
import io
import json
from pathlib import Path
import plistlib
import socket
import stat
import threading
from urllib.parse import parse_qs, urlsplit

import httpx
import pandas as pd
import pytest

from autopsy import cli
from autopsy.alerts import notify
from autopsy.data.kite import KiteError, create_session, read_session
from autopsy.data.kite_login import KiteLoginListener, wait_seconds
from autopsy.data import kite_login


TOKEN, ACCESS, SECRET = 'InventedRequestToken', 'InventedAccessToken', 'InventedSecret'
NOW = pd.Timestamp('2026-11-05 12:00', tz='Asia/Kolkata')


@pytest.fixture
def files(tmp_path):
    credentials = tmp_path / 'credentials.json'
    credentials.write_text(json.dumps({'api_key': 'InventedKey', 'api_secret': SECRET}))
    credentials.chmod(0o600)
    return credentials, tmp_path / 'session.json'


@pytest.fixture
def loopback():
    # Workspace sandboxes may deny even local bind. Keep real HTTP coverage
    # runnable outside that restriction, without masking ordinary bind failures.
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', 0))
        except OSError as exc:
            if exc.errno in (errno.EPERM, errno.EACCES):
                pytest.skip('sandbox denies loopback bind; run locally for real HTTP coverage')
            raise


@pytest.fixture
def idle_server(monkeypatch):
    class IdleServer:
        server_port = 0
        closed = False
        def __init__(self, *args):
            pass
        def handle_request(self):
            pass
        def server_close(self):
            self.closed = True
    monkeypatch.setattr(kite_login, '_Server', IdleServer)


@pytest.fixture
def memory_server(monkeypatch):
    """Run the real HTTP handler/parser against byte streams, without sockets."""
    class Connection:
        def __init__(self, request):
            self.input = io.BytesIO(request)
            self.output = bytearray()
        def makefile(self, mode, buffering):
            return self.input
        def sendall(self, data):
            self.output.extend(data)
    class MemoryServer:
        server_port = 0
        closed = False
        def __init__(self, address, handler):
            self.handler = handler
            self.requests = []
            self.responses = []
        def handle_request(self):
            if self.requests:
                connection = Connection(self.requests.pop(0))
                self.handler(connection, ('127.0.0.1', 12345), self)
                self.responses.append(bytes(connection.output).decode())
        def server_close(self):
            self.closed = True
    monkeypatch.setattr(kite_login, '_Server', MemoryServer)


def test_http_handler_parser_retries_and_sanitizes_without_sockets(files, memory_server, capsys):
    calls = []
    def retry(*args):
        calls.append(args)
        if len(calls) == 1:
            raise KiteError(SECRET + ACCESS + TOKEN)
        return exchange(*args)
    with KiteLoginListener(*files, port=0, wait='5s', exchange=retry) as listener:
        callback = CALLBACK + '&state=' + listener.state
        for request, status in [
            (f'BAD {TOKEN} extra HTTP/1.0\r\n\r\n', 400),
            ('GET /favicon.ico HTTP/1.0\r\nHost: localhost:0\r\n\r\n', 404),
            (f'GET /wrong?request_token={TOKEN} HTTP/1.0\r\nHost: localhost:0\r\n\r\n', 404),
            (f'GET {callback.replace("status=success", "status=error")} HTTP/1.0\r\nHost: localhost:0\r\n\r\n', 400),
            (f'GET {callback} HTTP/1.0\r\nHost: localhost:0\r\n\r\n', 400),
            (f'GET {callback} HTTP/1.0\r\nHost: localhost:0\r\n\r\n', 200),
        ]:
            listener.server.requests.append(request.encode())
            listener.server.handle_request()
            assert f' {status} ' in listener.server.responses[-1].splitlines()[0]
        assert listener.wait()['access_token'] == ACCESS
        responses = ''.join(listener.server.responses)
    assert len(calls) == 2
    assert stat.S_IMODE(files[1].stat().st_mode) == 0o600
    assert 'Kite login saved. You can close this tab.' in responses
    captured = capsys.readouterr()
    assert all(value not in responses + captured.out + captured.err
               for value in [TOKEN, ACCESS, SECRET, listener.state])


def test_cli_notify_and_capture_without_sockets(files, monkeypatch, memory_server, capsys):
    listeners, reminders, opened = [], [], []
    def listener(*args, **kwargs):
        result = KiteLoginListener(*args, **kwargs)
        result.server.requests.append(
            f'GET {CALLBACK}&state={result.state} HTTP/1.0\r\nHost: 127.0.0.1:0\r\n\r\n'.encode())
        listeners.append(result)
        return result
    def browser(url):
        assert listeners and reminders  # Bound and notified before opening.
        opened.append(url)
    monkeypatch.setattr(cli, 'KiteLoginListener', listener)
    monkeypatch.setattr(cli, 'create_session', exchange)
    monkeypatch.setattr(cli, 'notify_kite_login', lambda: reminders.append(True))
    monkeypatch.setattr(cli.webbrowser, 'open', browser)
    assert cli.main(args_for(files) + ['--notify']) == 0
    assert len(opened) == 1 and reminders == [True]
    query = parse_qs(urlsplit(opened[0]).query)
    assert parse_qs(query['redirect_params'][0]) == {'state': [listeners[0].state]}
    captured = capsys.readouterr()
    assert 'Kite session saved; valid until' in captured.out
    assert all(value not in captured.out + captured.err
               for value in [TOKEN, ACCESS, SECRET, listeners[0].state])


def test_cli_bind_failure_sanitized_without_sockets(files, monkeypatch, capsys):
    def busy(*args):
        raise OSError(errno.EADDRINUSE, SECRET + TOKEN)
    monkeypatch.setattr(kite_login, '_Server', busy)
    monkeypatch.setattr(cli.webbrowser, 'open', lambda *a: pytest.fail('bind first'))
    assert cli.main(args_for(files) + ['--port', '8742']) == 2
    err = capsys.readouterr().err
    assert '8742' in err and '--paste' in err and 'Traceback' not in err
    assert SECRET not in err and TOKEN not in err


def exchange(credentials, session, token):
    assert token == TOKEN
    return create_session(credentials, session, token, now=NOW, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={'status': 'success', 'data': {
            'access_token': ACCESS, 'login_time': NOW.isoformat()}})))


def get(port, path):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        connection.request('GET', path)
        response = connection.getresponse()
        return response.status, response.read().decode()
    finally:
        connection.close()


CALLBACK = '/kite?status=success&request_token=' + TOKEN


@pytest.mark.parametrize('suffix,host', [
    ('', '127.0.0.1:0'),
    ('&state=wrong', '127.0.0.1:0'),
    ('&state=', '127.0.0.1:0'),
    ('&state=%C3%A9', '127.0.0.1:0'),
    ('&state={state}&state={state}', '127.0.0.1:0'),
    ('&state={state}&state=', '127.0.0.1:0'),
    ('&state={state}', 'attacker.example:0'),
    ('&state={state}', '127.0.0.1:8742'),
    ('&state={state}', 'localhost'),
    ('&state={state}', ''),
    ('&state={state}', '127.0.0.1:0\r\nHost: localhost:0'),
])
def test_callback_rejected_before_exchange(files, memory_server, capsys, caplog, suffix, host):
    calls = []
    def capture(*args):
        calls.append(args)
        return exchange(*args)
    with KiteLoginListener(*files, port=0, exchange=capture) as listener:
        path = CALLBACK + suffix.format(state=listener.state)
        header = f'Host: {host}\r\n' if host else ''
        listener.server.requests.append(f'GET {path} HTTP/1.0\r\n{header}\r\n'.encode())
        listener.server.handle_request()
        response = listener.server.responses[-1]
        assert ' 400 ' in response.splitlines()[0]
        assert calls == [] and listener.session is None
        assert not files[1].exists()
        # A rejected request does not prevent a subsequent valid login.
        listener.server.requests.append(
            f'GET {CALLBACK}&state={listener.state} HTTP/1.0\r\nHost: localhost:0\r\n\r\n'.encode())
        assert listener.wait()['access_token'] == ACCESS
        assert len(calls) == 1
    captured = capsys.readouterr()
    assert all(value not in ''.join(listener.server.responses) + captured.out + captured.err + caplog.text
               for value in [TOKEN, ACCESS, SECRET, listener.state, path])


@pytest.mark.parametrize('failure', ['state', 'status', 'token', 'exchange', 'mixed'])
def test_cli_five_invalid_callbacks_abort(files, monkeypatch, memory_server, capsys, caplog, failure):
    listeners, calls = [], []
    def fail_exchange(*args):
        calls.append(args)
        raise KiteError(SECRET + TOKEN + listeners[0].state)
    def listener(*args, **kwargs):
        result = KiteLoginListener(*args, **kwargs)
        listeners.append(result)
        valid = CALLBACK + '&state=' + result.state
        paths = {
            'state': CALLBACK,
            'status': valid.replace('status=success', 'status=error'),
            'token': valid.replace(TOKEN, 'bad%2Ftoken'),
            'exchange': valid,
        }
        failures = ['state', 'status', 'token', 'exchange', 'state'] if failure == 'mixed' else [failure] * 5
        for kind in failures:
            result.server.requests.append(
                f'GET {paths[kind]} HTTP/1.0\r\nHost: localhost:0\r\n\r\n'.encode())
        # This valid sixth request must never be consumed after the limit.
        result.server.requests.append(
            f'GET {valid} HTTP/1.0\r\nHost: localhost:0\r\n\r\n'.encode())
        return result
    monkeypatch.setattr(cli, 'KiteLoginListener', listener)
    monkeypatch.setattr(cli, 'create_session', fail_exchange)
    monkeypatch.setattr(cli.webbrowser, 'open', lambda *a: pytest.fail('no browser requested'))
    assert cli.main(args_for(files) + ['--no-browser']) == 2
    result = listeners[0]
    assert result.server.closed and result.failed_attempts == 5
    assert len(result.server.requests) == 1
    assert len(result.server.responses) == 5
    assert all(' 400 ' in response.splitlines()[0] for response in result.server.responses)
    assert len(calls) == (5 if failure == 'exchange' else 1 if failure == 'mixed' else 0)
    assert not files[1].exists()
    captured = capsys.readouterr()
    assert 'Too many invalid Kite login callbacks; run autopsy kite login again' in captured.err
    assert 'Traceback' not in captured.err
    assert all(value not in captured.out + captured.err + ''.join(result.server.responses) + caplog.text
               for value in [TOKEN, ACCESS, SECRET, result.state])


def test_state_is_fresh_per_listener(files, memory_server):
    with KiteLoginListener(*files) as first, KiteLoginListener(*files) as second:
        assert first.state != second.state
        assert len(first.state) == len(second.state) == 43


def test_listener_real_http_private_session_and_retry(files, capsys, caplog, loopback):
    calls = []
    def retry(*args):
        calls.append(args)
        if len(calls) == 1:
            raise KiteError(SECRET + ACCESS + TOKEN)
        return exchange(*args)
    with KiteLoginListener(*files, port=0, wait='5s', exchange=retry) as listener:
        assert listener.server.server_address[0] == '127.0.0.1'
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(listener.wait)
            for path in ['/favicon.ico', '/wrong', '/kite/']:
                assert get(listener.port, path)[0] == 404
                assert not waiting.done()
            for path in ['/kite?status=error&request_token=' + TOKEN,
                         '/kite?status=success&request_token=bad%2Ftoken',
                         '/kite?status=success&request_token=A&request_token=B']:
                assert get(listener.port, path + '&state=' + listener.state) == (400, '<!doctype html><meta charset="utf-8"><p>Login failed; try again</p>')
                assert not waiting.done()
            assert calls == []
            failed = get(listener.port, CALLBACK + '&state=' + listener.state)
            assert failed[0] == 400
            status, body = get(listener.port, CALLBACK + '&state=' + listener.state)
            assert status == 200 and 'Kite login saved. You can close this tab.' in body
            assert waiting.result(timeout=2)['access_token'] == ACCESS
    assert len(calls) == 2
    assert stat.S_IMODE(files[1].stat().st_mode) == 0o600
    assert read_session(files[1], now=NOW)['access_token'] == ACCESS
    captured = capsys.readouterr()
    assert all(value not in body + failed[1] + captured.out + captured.err + caplog.text
               for value in [TOKEN, ACCESS, SECRET, listener.state])
    # Context manager releases the listening socket after success.
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', listener.port)) != 0


def test_listener_injected_deadline_closes(files, idle_server):
    times = iter([0., 91.])
    with pytest.raises(KiteError, match='No Kite login within 90s'):
        with KiteLoginListener(*files, port=0, wait='90s', clock=lambda: next(times),
                               exchange=lambda *a: pytest.fail('no exchange')) as listener:
            listener.wait()
    assert listener.server.closed


@pytest.mark.parametrize('value,seconds', [('90s', 90), ('10m', 600), ('18h', 64800), ('17h', 61200)])
def test_wait_duration(value, seconds):
    assert wait_seconds(value) == seconds


@pytest.mark.parametrize('value', ['0s', '-1h', '1d', 'NaNs', 'infh', '10', ''])
def test_bad_wait(value):
    with pytest.raises(ValueError, match='positive duration'):
        wait_seconds(value)


def args_for(files):
    return ['kite', 'login', '--credentials', str(files[0]), '--session', str(files[1])]


def test_cli_timeout_clean_and_silent(files, monkeypatch, capsys, idle_server):
    monkeypatch.setattr(cli, 'create_session', lambda *a: pytest.fail('no exchange'))
    assert cli.main(args_for(files) + ['--port', '0', '--wait', '0.01s', '--no-browser']) == 2
    captured = capsys.readouterr()
    assert 'No Kite login within 0.01s; run autopsy kite login again' in captured.err
    assert 'Traceback' not in captured.err
    assert all(value not in captured.out + captured.err for value in [TOKEN, ACCESS, SECRET])


def test_cli_busy_port_does_not_open_browser(files, monkeypatch, capsys, loopback):
    monkeypatch.setattr(cli.webbrowser, 'open', lambda *a: pytest.fail('must bind first'))
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        assert cli.main(args_for(files) + ['--port', str(port)]) == 2
    err = capsys.readouterr().err
    assert str(port) in err and '--paste' in err and 'Traceback' not in err


def test_cli_default_capture_notify_opens_browser(files, monkeypatch, capsys, loopback):
    listeners, opened, reminders, responses = [], [], [], []
    def listener(*a, **kw):
        result = KiteLoginListener(*a, **kw)
        listeners.append(result)
        return result
    threads = []
    def browser(url):
        opened.append(url)
        thread = threading.Thread(target=lambda: responses.append(
            get(listeners[0].port, CALLBACK + '&state=' + listeners[0].state)))
        threads.append(thread)
        thread.start()
        return True
    monkeypatch.setattr(cli, 'KiteLoginListener', listener)
    monkeypatch.setattr(cli, 'create_session', exchange)
    monkeypatch.setattr(cli, 'notify_kite_login', lambda: reminders.append(True))
    monkeypatch.setattr(cli.webbrowser, 'open', browser)
    assert cli.main(args_for(files) + ['--port', '0', '--notify', '--wait', '5s']) == 0
    for thread in threads:
        thread.join(timeout=3)
        assert not thread.is_alive()
    assert len(opened) == 1 and reminders == [True]
    assert responses[0][0] == 200
    captured = capsys.readouterr()
    assert 'Kite session saved; valid until 2026-11-06 06:00:00 IST' in captured.out
    assert all(value not in captured.out + captured.err + responses[0][1]
               for value in [TOKEN, ACCESS, SECRET, listeners[0].state])


@pytest.mark.parametrize('remaining,skip', [(31, True), (30, True), (29, False), (0, False)])
def test_if_needed_validates_actual_session_and_threshold(files, monkeypatch, capsys, remaining, skip, idle_server):
    exchange(*files, TOKEN)
    if skip:
        files[0].unlink()  # No credentials or notification needed for a valid session.
    real_timestamp = pd.Timestamp
    class FixedTimestamp(real_timestamp):
        @classmethod
        def now(cls, tz=None):
            return real_timestamp('2026-11-06 06:00', tz='Asia/Kolkata') - pd.Timedelta(minutes=remaining)
    monkeypatch.setattr(cli.pd, 'Timestamp', FixedTimestamp)
    opened = []
    monkeypatch.setattr(cli.webbrowser, 'open', lambda url: opened.append(url))
    monkeypatch.setattr(cli, 'notify_kite_login', lambda: pytest.fail('no notification requested'))
    result = cli.main(args_for(files) + ['--if-needed', '--port', '0', '--wait', '0.01s']
                      + (['--notify'] if skip else []))
    captured = capsys.readouterr()
    assert result == (0 if skip else 2)
    assert len(opened) == (0 if skip else 1)
    assert ('Kite session already valid until' in captured.out) == skip


@pytest.mark.parametrize('configured', [False, True])
def test_notifier_mac_and_only_configured_telegram(tmp_path, monkeypatch, configured):
    path = tmp_path / 'telegram.json'
    if configured:
        path.write_text('{}')
    monkeypatch.setattr(notify, 'TELEGRAM_CONFIG', path)
    mac, telegram = [], []
    monkeypatch.setattr(notify.MacNotifier, 'send', lambda self, text: mac.append(text))
    class FakeTelegram:
        def send(self, text):
            telegram.append(text)
    monkeypatch.setattr(notify, 'TelegramNotifier', FakeTelegram)
    notify.notify_kite_login()
    assert len(mac) == 1 and telegram == (mac if configured else [])
    assert "Oracle Autopsy: log in to Kite for tonight's run" in mac[0]
    assert 'on this Mac, not a phone' in mac[0]


def test_launchagent_template():
    path = Path(__file__).parents[1] / 'deploy/com.oracleautopsy.kite-login.plist.example'
    config = plistlib.loads(path.read_bytes())
    assert config['ProgramArguments'] == ['__REPO__/.venv/bin/autopsy', 'kite', 'login',
                                          '--if-needed', '--notify', '--wait', '17h']
    assert config['StartCalendarInterval'] == [
        {'Weekday': day, 'Hour': 15, 'Minute': 45} for day in range(1, 6)]
    for key in ['StandardOutPath', 'StandardErrorPath']:
        assert config[key].startswith('__HOME__/oracle-autopsy-data/logs/')
