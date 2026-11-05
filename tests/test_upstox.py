import json
import logging
from pathlib import Path
import subprocess
import sys
import traceback

import httpx
import pandas as pd
import pytest

from autopsy.cli import main
from autopsy.data.upstox import TokenMissing, UpstoxClient, UpstoxError


@pytest.fixture
def token(tmp_path):
    path = tmp_path / "analytics_token"
    path.write_text("SECRET123\n")
    path.chmod(0o600)
    return path


def fixture_payload():
    return json.loads((Path(__file__).parent / "fixtures/upstox/candles.json").read_text())


def test_upstox_chunking(token):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer SECRET123"
        assert b"NSE_EQ%7CINVENTED" in request.url.raw_path
        payload = fixture_payload()
        start = request.url.path.rsplit("/", 1)[1]
        for row in payload["data"]["candles"]:
            row[0] = start + row[0][10:]
        return httpx.Response(200, json=payload)

    client = UpstoxClient(token, transport=httpx.MockTransport(handle), cache=False)
    result = client.candles("NSE_EQ|INVENTED", "minutes", 5, "2025-01-01", "2025-03-31")
    assert len(requests) == 3
    assert [r.url.path.rsplit("/", 2)[-2:] for r in requests] == [
        ["2025-01-31", "2025-01-01"], ["2025-02-28", "2025-02-01"],
        ["2025-03-31", "2025-03-01"]]
    assert str(result.index.tz) == "Asia/Kolkata"
    assert result.index.is_monotonic_increasing
    assert len(result) == 6
    assert len(json.loads(result.attrs["expected_bars"])) == 9  # Missing 09:20 in each chunk.
    assert result.close.tolist() == [100., 102.] * 3


def test_upstox_429_backoff(token):
    attempts, waits = [], []

    def handle(request):
        attempts.append(request)
        return httpx.Response(429) if len(attempts) < 4 else httpx.Response(200, json=fixture_payload())

    client = UpstoxClient(token, transport=httpx.MockTransport(handle), sleep=waits.append, cache=False)
    client.candles("NSE_EQ|INVENTED", "minutes", 5, "2025-01-01", "2025-01-01")
    assert waits == [1., 2., 4.]
    assert len(attempts) == 4


def test_missing_token_message(tmp_path):
    path = tmp_path / "missing_token"
    proc = subprocess.run([sys.executable, "-m", "autopsy.cli", "data", "fetch-upstox",
                           "--token-path", str(path), "--symbols", str(tmp_path / "symbols.txt"),
                           "--from", "2025-01-01"], capture_output=True, text=True)
    assert proc.returncode == 2
    output = proc.stdout + proc.stderr
    assert str(path) in output
    assert "Upstox → Developer Apps → Analytics → generate token" in output
    assert "Traceback" not in output


@pytest.mark.parametrize("failure", [401, 403, 500, 429, "transport", "json"])
def test_token_never_logged(token, caplog, failure):
    caplog.set_level(logging.DEBUG)

    def handle(request):
        if failure == "transport":
            raise httpx.ReadError("SECRET123", request=request)
        if failure == "json":
            return httpx.Response(200, text="SECRET123")
        return httpx.Response(failure, text="SECRET123")

    client = UpstoxClient(token, transport=httpx.MockTransport(handle), sleep=lambda _: None, cache=False)
    with pytest.raises((TokenMissing, UpstoxError)) as exc:
        client.candles("NSE_EQ|INVENTED", "minutes", 5, "2025-01-01", "2025-01-01")
    rendered = "".join(traceback.format_exception(exc.type, exc.value, exc.tb))
    assert "SECRET123" not in str(exc.value) + rendered + caplog.text + repr(client)
    if failure in (401, 403):
        assert str(token) in str(exc.value)


def test_expired_token_cli(token, tmp_path, monkeypatch, capsys):
    client = UpstoxClient(token, transport=httpx.MockTransport(lambda _: httpx.Response(401)), cache=False)
    monkeypatch.setattr("autopsy.cli.UpstoxClient", lambda **_: client)
    symbols = tmp_path / "symbols.txt"
    symbols.write_text("NSE_EQ|INVENTED\n")
    assert main(["data", "fetch-upstox", "--symbols", str(symbols), "--from", "2025-01-01",
                 "--to", "2025-01-02"]) == 2
    output = capsys.readouterr().err
    assert str(token) in output and "Traceback" not in output and "SECRET123" not in output


def test_upstox_cache_and_validation(token, tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=fixture_payload())

    client = UpstoxClient(token, transport=httpx.MockTransport(handle), cache_dir=tmp_path / "cache")
    args = ("NSE_EQ|INVENTED", "minutes", 5, "2025-01-01", "2025-01-01")
    pd.testing.assert_frame_equal(client.candles(*args), client.candles(*args))
    assert len(calls) == 1
    for unit, interval, start in [("minutes", 301, "2025-01-01"), ("hours", 6, "2025-01-01"),
                                  ("days", 2, "2025-01-01"), ("minutes", 5, "2021-12-31")]:
        with pytest.raises(ValueError):
            client.candles("NSE_EQ|INVENTED", unit, interval, start, "2025-01-02")
    with pytest.raises(ValueError, match="tz-aware"):
        client.candles("NSE_EQ|INVENTED", "minutes", 5, pd.Timestamp("2025-01-01"), "2025-01-02")
    assert len(calls) == 1


def test_adjusted_upstox_cannot_apply_actions_again(token, tmp_path, monkeypatch):
    from autopsy.data.corporate import with_actions
    from autopsy.data.store import load_snapshot
    client = UpstoxClient(token, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=fixture_payload())), cache_dir=tmp_path / 'cache')
    args = ('NSE_EQ|INVENTED', 'minutes', 5, '2025-01-01', '2025-01-01')
    for frame in [client.candles(*args), client.candles(*args)]:
        assert frame.attrs['price_basis'] == 'adjusted'
        with pytest.raises(ValueError, match='raw, not adjusted'):
            with_actions(frame, pd.DataFrame())
    path, = (tmp_path / 'cache').glob('*.parquet')
    cached, meta = load_snapshot(path)
    assert cached.attrs['price_basis'] == meta['kind'] == 'adjusted'
    monkeypatch.setenv('AUTOPSY_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr('autopsy.cli.UpstoxClient', lambda **_: client)
    symbols = tmp_path / 'symbols.txt'
    symbols.write_text('NSE_EQ|INVENTED\n')
    assert main(['data', 'fetch-upstox', '--symbols', str(symbols), '--from', '2025-01-01',
                 '--to', '2025-01-01']) == 0
    state = json.loads((tmp_path / 'data/session.json').read_text())
    frame, meta = load_snapshot(state['prices_path'])
    assert frame.attrs['price_basis'] == meta['kind'] == 'adjusted'
