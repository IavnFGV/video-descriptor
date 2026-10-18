import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from video_descriptor import diagnostics, jobs


def test_managed_worker_does_not_spawn_duplicates(tmp_path, monkeypatch):
    monkeypatch.setenv('VIDEO_DESCRIPTOR_MANAGED_WORKER', '1')
    spawn = Mock()
    monkeypatch.setattr(jobs.subprocess, 'Popen', spawn)
    jobs.start_worker(tmp_path)
    spawn.assert_not_called()


def test_interrupted_job_retains_results_and_is_not_retried(tmp_path):
    folder = jobs.jobs_dir(tmp_path) / 'interrupted'
    folder.mkdir()
    jobs.write_json(folder / 'job.json', {'status': 'running', 'id': 'interrupted'})
    (folder / 'checkpoint.json').write_text('{"done":1}')
    jobs.worker(tmp_path, stay_alive=False)
    assert jobs.read_json(folder / 'job.json')['status'] == 'error'
    assert json.loads((folder / 'checkpoint.json').read_text()) == {'done': 1}


@pytest.mark.parametrize('code,status', [(200, 'ok'), (403, 'invalid_key'), (429, 'unavailable')])
def test_diagnostics_redacts_remote_bodies_and_keys(tmp_path, monkeypatch, code, status):
    monkeypatch.setenv('GEMINI_API_KEY', 'secret-never-returned')
    monkeypatch.setenv('OLLAMA_MODEL', 'present')
    ollama = Mock()
    ollama.json.return_value = {'models': [{'name': 'present'}]}
    gemini = Mock(ok=code == 200, status_code=code, text='secret-never-returned')
    monkeypatch.setattr(diagnostics.requests, 'get', Mock(side_effect=[ollama, gemini]))
    result = diagnostics.connections(tmp_path)
    assert result['ollama']['status'] == 'ok'
    assert result['gemini']['status'] == status
    assert 'secret-never-returned' not in json.dumps(result)


def test_diagnostics_without_optional_services(tmp_path, monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setattr(diagnostics.requests, 'get', Mock(side_effect=requests.ConnectionError('secret')))
    result = diagnostics.connections(tmp_path)
    assert result['ollama']['status'] == 'unavailable'
    assert result['gemini']['status'] == 'missing_key'
    assert 'secret' not in json.dumps(result)


@pytest.mark.skipif(sys.platform != 'linux', reason='Container supervisor uses Linux process groups')
def test_real_supervisor_signals_and_worker_failure(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    folder = jobs.jobs_dir(tmp_path) / 'interrupted'
    folder.mkdir()
    jobs.write_json(folder / 'job.json', {'status': 'running', 'id': 'interrupted'})
    command = [sys.executable, '-m', 'video_descriptor.container_runtime', '--port', str(port)]
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}

    def launch():
        process = subprocess.Popen(command, cwd=tmp_path, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while True:
            try:
                if requests.get(f'http://127.0.0.1:{port}/health', timeout=.5).status_code == 200:
                    return process
            except requests.RequestException:
                pass
            if process.poll() is not None or time.monotonic() > deadline:
                process.terminate()
                process.wait(timeout=15)
                raise AssertionError('Supervisor HTTP did not start')
            time.sleep(.1)

    first = launch()
    try:
        deadline = time.monotonic() + 5
        while jobs.read_json(folder / 'job.json')['status'] != 'error':
            assert time.monotonic() < deadline
            time.sleep(.1)
    finally:
        first.send_signal(signal.SIGTERM)
        assert first.wait(timeout=15) == 0
    second = launch()
    try:
        children = Path(f'/proc/{second.pid}/task/{second.pid}/children').read_text().split()
        workers = [pid for pid in children if b'video_descriptor.jobs' in
                   Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')]
        assert len(workers) == 1
        os.kill(int(workers[0]), signal.SIGKILL)
        assert second.wait(timeout=15) == 1
    finally:
        if second.poll() is None:
            second.terminate()
            second.wait(timeout=15)
    assert jobs.read_json(folder / 'job.json')['status'] == 'error'
