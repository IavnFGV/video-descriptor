"""Real backend subprocess checks without models, Docker, or the user's workspace."""
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'windows-app'))
spec = importlib.util.spec_from_file_location('desktop_policy', ROOT / 'windows-app/desktop.py')
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-data"))
    shutil.copytree(ROOT / 'video_descriptor', tmp_path / 'video_descriptor',
                    ignore=shutil.ignore_patterns('__pycache__'))
    folder = tmp_path / 'windows-app'
    folder.mkdir()
    for name in ('app.py', 'desktop.py', 'compute.py', 'setup_service.py', 'component_manager.py', 'model_download.py', 'component-manifest.json'):
        shutil.copyfile(ROOT / 'windows-app' / name, folder / name)
    shutil.copytree(ROOT / 'windows-app/ui', folder / 'ui')
    (tmp_path / 'scripts').mkdir()
    shutil.copyfile(ROOT / 'scripts/whisper_npu_server.py', tmp_path / 'scripts/whisper_npu_server.py')
    value = json.loads((ROOT / 'windows-app/config.example.json').read_text())
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        value['port'] = probe.getsockname()[1]
    (folder / 'config.example.json').write_text(json.dumps(value))
    yield folder, f'http://127.0.0.1:{value["port"]}'
    subprocess.run([sys.executable, str(folder / 'app.py'), '--stop'], check=False, capture_output=True,
                   timeout=10, env={**os.environ, 'PYTHONUTF8': '1'})


def connection(folder):
    return subprocess.run([sys.executable, str(folder / 'desktop.py')], check=False, capture_output=True,
                          encoding='utf-8', timeout=40, env={**os.environ, 'PYTHONUTF8': '1'})


def test_desktop_launch_repeat_api_and_active_job_survives(installation):
    folder, base = installation
    first = connection(folder)
    assert first.returncode == 0, first.stderr
    session = json.loads(first.stdout)
    second = connection(folder)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout) == session
    assert requests.get(base, timeout=3).status_code == 200
    job = folder / 'runtime/workspace/output/jobs/active/job.json'
    job.parent.mkdir(parents=True)
    job.write_text('{"status":"running"}')
    try:
        response = requests.post(base + '/api/native/stop',
                                 headers={'X-App-Instance': session['instance']}, timeout=3)
        assert response.status_code == 409
        assert requests.get(base + '/health', timeout=3).json()['instance'] == session['instance']
    finally:
        job.write_text('{"status":"done"}')
    assert requests.get(base + '/health', headers={'Host': 'evil.example'}, timeout=3).status_code == 403
    for origin in ('https://example.org', 'https://' + base.split('//')[1], 'null'):
        assert requests.get(base + '/health', headers={'Origin': origin}, timeout=3).status_code == 403
    assert requests.get(base + '/health', headers={'Sec-Fetch-Site': 'cross-site'}, timeout=3).status_code == 403


@pytest.mark.parametrize('payload', [b'{"status":"ok"}', b'{"app":"video-descriptor-windows"}', b'not json'])
def test_foreign_listener_is_never_started_or_stopped(installation, payload):
    folder, base = installation

    class Foreign(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', int(base.rsplit(':', 1)[1])), Foreign)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = connection(folder)
        assert result.returncode == 1
        assert 'Порт занят' in result.stderr
        assert not list((folder / 'runtime').glob('instance-*.json'))
        assert requests.get(base + '/health', timeout=3).content == payload
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_failed_backend_reports_log_path(installation):
    folder, _ = installation
    (folder / 'compute.py').unlink()
    result = connection(folder)
    assert result.returncode == 1
    assert 'runtime/logs/desktop-backend.log' in result.stderr


def test_concurrent_launches_connect_to_one_backend(installation):
    folder, _ = installation
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(connection, [folder, folder]))
    assert all(result.returncode == 0 for result in results), [r.stderr for r in results]
    assert json.loads(results[0].stdout) == json.loads(results[1].stdout)


def test_identity_requires_installation_workspace_and_recorded_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop.app, 'HERE', tmp_path)
    value = {'workspace': str(tmp_path / 'runtime/workspace')}
    state = desktop.state_path(value)
    state.parent.mkdir()
    state.write_text('{"instance":"owned"}', encoding='utf-8')
    info = {'app': desktop.app.APP, 'workspace': value['workspace'], 'instance': 'owned',
            'installation': desktop.app.installation_id(), 'desktop_protocol': 1}
    assert desktop.identity(info, value)
    for key in ('app', 'workspace', 'instance', 'installation', 'desktop_protocol'):
        assert not desktop.identity({**info, key: 'foreign'}, value)
    state.unlink()
    assert not desktop.identity(info, value)


def test_timeout_does_not_terminate_child(tmp_path, monkeypatch):
    class Child:
        def poll(self):
            return None

    monkeypatch.setattr(desktop.app, 'HERE', tmp_path)
    monkeypatch.setattr(desktop.app, 'fetch', lambda *a, **k: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(desktop.subprocess, 'Popen', lambda *a, **k: Child())
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    with pytest.raises(ValueError, match='не готов'):
        desktop.connect({'port': port}, timeout=0)
