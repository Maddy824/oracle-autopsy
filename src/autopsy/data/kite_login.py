"""One-shot loopback login capture. Never log callback URLs or credentials."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import math
import re
import secrets
import time
from urllib.parse import parse_qs, urlsplit

from autopsy.data.kite import KiteError, create_session, parse_request_token


def wait_seconds(value):
    """Parse positive durations such as 90s, 10m or 18h."""
    match = re.fullmatch(r'(\d+(?:\.\d+)?)([smh])', value)
    if match:
        seconds = float(match[1]) * {'s': 1, 'm': 60, 'h': 3600}[match[2]]
        if math.isfinite(seconds) and seconds > 0:
            return seconds
    raise ValueError('Kite --wait must be a positive duration such as 90s, 10m or 18h.')


class _Server(HTTPServer):
    def handle_error(self, request, client_address):
        # The default prints a traceback which could contain callback data.
        pass

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(min(1., max(.001, self.deadline - self.clock())))
        return connection, address


class KiteLoginListener:
    """Bind before opening the browser; close on success, timeout or cancellation.

    Port 0 exposes an ephemeral port via ``port``. Exchange and monotonic clock
    are injectable; no password or TOTP is handled here.
    """

    def __init__(self, credentials_path, session_path, *, port=8742, wait='10m',
                 exchange=None, clock=time.monotonic):
        seconds = wait_seconds(wait)
        if not 0 <= port <= 65535:
            raise KiteError('Kite --port must be between 0 and 65535.')
        self.session = None
        self.state = secrets.token_urlsafe(32)
        self.failed_attempts = 0
        self.wait_label = wait
        self.clock = clock
        self.deadline = clock() + seconds
        exchange = exchange or create_session
        listener = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def send_error(self, code, message=None, explain=None):
                # BaseHTTPRequestHandler's default error page can echo a
                # malformed request line, including its sensitive query.
                self.page(code, 'Invalid login request')

            def page(self, status, message):
                body = ('<!doctype html><meta charset="utf-8"><p>' + message + '</p>').encode()
                self.send_response(status)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                hosts = self.headers.get_all('Host', [])
                if len(hosts) != 1 or hosts[0] not in (
                        f'127.0.0.1:{listener.port}', f'localhost:{listener.port}'):
                    self.page(400, 'Login failed; try again')
                    return
                try:
                    url = urlsplit(self.path)
                except ValueError:
                    self.page(400, 'Login failed; try again')
                    return
                if url.path != '/kite':
                    self.page(404, 'Not found')
                    return
                if listener.clock() >= listener.deadline:
                    self.page(408, 'Login timed out; run autopsy kite login again')
                    return
                if not listener.accept(url.query):
                    self.page(400, 'Login failed; try again')
                    return
                self.page(200, 'Kite login saved. You can close this tab.')

        try:
            self.server = _Server(('127.0.0.1', port), Handler)
        except OSError:
            raise KiteError(f'Cannot listen for Kite login on 127.0.0.1 port {port}; '
                            'the port may be busy. Use autopsy kite login --paste.') from None
        self.server.deadline, self.server.clock = self.deadline, clock
        self.port = self.server.server_port
        self._exchange = lambda token: exchange(credentials_path, session_path, token)

    def accept(self, query):
        """Validate one redirect query (state, status, token) and exchange it.

        Shared by the loopback callback and a redirect URL pasted back from a
        phone (e.g. via the owner's Telegram chat). Returns True on success.
        """
        if self.session is not None:
            return True
        try:
            parsed = parse_qs(query, keep_blank_values=True)
            states = parsed.get('state', [])
            if len(states) != 1 or not hmac.compare_digest(states[0].encode(), self.state.encode()):
                raise ValueError()
            if parsed.get('status') != ['success']:
                raise ValueError()
            token = parse_request_token('http://127.0.0.1/kite?' + query)
            self.session = self._exchange(token)
        except Exception:
            # Even an injected exchange must never echo its exception.
            self.failed_attempts += 1
            return False
        return True

    def accept_pasted(self, text):
        """Accept a pasted http://127.0.0.1:<port>/kite?... redirect URL from a phone."""
        match = re.search(r'https?://(?:127\.0\.0\.1|localhost):\d+/kite\?(\S+)', text or '')
        if not match:
            return False
        return self.accept(match[1])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.server.server_close()

    def wait(self, poll=None, poll_every=3.):
        """poll() returns pasted texts (e.g. new Telegram messages); checked every poll_every s."""
        next_poll = self.clock() if poll is not None else None
        while self.session is None:
            if poll is not None and self.clock() >= next_poll:
                next_poll = self.clock() + poll_every
                for text in poll():
                    if self.accept_pasted(text):
                        break
                if self.session is not None:
                    break
            if self.failed_attempts >= 5:
                raise KiteError('Too many invalid Kite login callbacks; run autopsy kite login again')
            remaining = self.deadline - self.clock()
            if remaining <= 0:
                raise KiteError(f'No Kite login within {self.wait_label}; run autopsy kite login again')
            self.server.timeout = min(1., remaining)
            self.server.handle_request()
        return self.session
