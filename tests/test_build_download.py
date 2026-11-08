import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest

from video_descriptor.platform_support import windows_shell_environment

spec = importlib.util.spec_from_file_location('build_download', Path(__file__).resolve().parents[1] / 'scripts/download_build_file.py')
download = importlib.util.module_from_spec(spec)
spec.loader.exec_module(download)
PAYLOAD = b'verified build tool'
SHA = hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(download.time, 'sleep', lambda _: None)


def test_transient_504_retries_and_publishes_only_verified_bytes(tmp_path, monkeypatch, no_sleep):
    target = tmp_path / 'inno.exe'
    opener = Mock(side_effect=[urllib.error.HTTPError('https://fixture', 504, 'Timeout', {}, None), io.BytesIO(PAYLOAD)])
    monkeypatch.setattr(download.urllib.request, 'urlopen', opener)
    assert download.verified_download('https://fixture', target, SHA) == target
    assert target.read_bytes() == PAYLOAD
    assert opener.call_count == 2
    assert opener.call_args.kwargs['timeout'] == 30
    assert not list(tmp_path.glob('*.part'))


def test_valid_cache_never_downloads(tmp_path, monkeypatch):
    target = tmp_path / 'archive'
    target.write_bytes(PAYLOAD)
    opener = Mock(side_effect=AssertionError('Must use verified cache'))
    monkeypatch.setattr(download.urllib.request, 'urlopen', opener)
    download.verified_download('https://fixture', target, SHA)
    opener.assert_not_called()


def test_corrupt_cache_and_truncated_response_are_recovered(tmp_path, monkeypatch, no_sleep):
    target = tmp_path / 'archive'
    target.write_bytes(b'old partial cache')
    opener = Mock(side_effect=[io.BytesIO(b'truncated'), io.BytesIO(PAYLOAD)])
    monkeypatch.setattr(download.urllib.request, 'urlopen', opener)
    download.verified_download('https://fixture', target, SHA)
    assert opener.call_count == 2
    assert target.read_bytes() == PAYLOAD
    assert not list(tmp_path.glob('*.part'))


@pytest.mark.parametrize('error,calls', [
    (urllib.error.HTTPError('https://fixture', 504, 'Timeout', {}, None), 4),
    (urllib.error.HTTPError('https://fixture', 404, 'Missing', {}, None), 1),
    (TimeoutError('Network timeout'), 4),
])
def test_failure_is_bounded_and_never_leaves_partial_cache(tmp_path, monkeypatch, no_sleep, error, calls):
    opener = Mock(side_effect=error)
    monkeypatch.setattr(download.urllib.request, 'urlopen', opener)
    with pytest.raises(type(error)):
        download.verified_download('https://fixture', tmp_path / 'archive', SHA)
    assert opener.call_count == calls
    assert not list(tmp_path.iterdir())


def test_checksum_mismatch_is_never_accepted(tmp_path, monkeypatch, no_sleep):
    monkeypatch.setattr(download.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(b'wrong tool'))
    with pytest.raises(ValueError, match='SHA256 mismatch'):
        download.verified_download('https://fixture', tmp_path / 'archive', SHA)
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell build-tool integration')
def test_powershell_retries_without_polluting_compiler_path(tmp_path):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            self.send_response(504 if len(calls) == 1 else 200)
            self.send_header('Content-Length', str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD)

        def log_message(self, *args):
            pass

    root = Path(__file__).resolve().parents[1]
    app = tmp_path / 'windows-app'
    app.mkdir()
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    shutil.copyfile(root / 'windows-app/Prepare-BuildTools.ps1', app / 'Prepare-BuildTools.ps1')
    shutil.copyfile(root / 'scripts/download_build_file.py', scripts / 'download_build_file.py')
    compiler = app / 'cache/inno-6.7.3/ISCC.exe'
    compiler.parent.mkdir(parents=True)
    compiler.write_bytes(b'fixture, never executed')
    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        (app / 'release-inputs.json').write_text(json.dumps({'inno': {'url': f'http://127.0.0.1:{server.server_port}/tool', 'sha256': SHA}}))
        quote = lambda path: "'" + str(path).replace("'", "''") + "'"
        # Signature verification is stubbed only for this non-executable fixture.
        command = "function Get-AuthenticodeSignature { [pscustomobject]@{Status='Valid'; SignerCertificate=[pscustomobject]@{Subject='CN=Pyrsys B.V.'}} }; "
        command += '& ' + quote(app / 'Prepare-BuildTools.ps1') + ' -CacheDirectory ' + quote(app / 'cache')
        try:
            result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command],
                                    check=False, capture_output=True, timeout=30, env=windows_shell_environment())
        finally:
            server.shutdown()
            thread.join(timeout=3)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert result.stdout.decode().strip() == str(compiler)
    assert len(calls) == 2
    assert (app / 'cache/innosetup-6.7.3.exe').read_bytes() == PAYLOAD
    assert not list((app / 'cache').glob('*.part'))
