"""External HTTP contract, live inventories and generation; no user services involved."""
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from video_descriptor.llm_provider import require_model
from video_descriptor.ollama_connection import DEFAULT_URL, endpoint_url, selected
from video_descriptor.ollama_provider import Ollama


def test_ui_endpoint_and_inventory_races():
    subprocess.run([shutil.which('node') or 'node', 'tests/ollama_ui.cjs'],
                   cwd=Path(__file__).resolve().parents[1], check=True, timeout=20)


@pytest.fixture
def server():
    state = {'models': [{'name': 'installed:latest', 'size': 42}], 'generation': {'done': True, 'response': 'ready'}, 'calls': []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state['calls'].append(self.path)
            value = {'version': 'test-1'} if self.path == '/api/version' else {'models': state['models']}
            data = json.dumps(value).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            state['calls'].append(self.path)
            state['body'] = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            data = json.dumps(state['generation']).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(data)

    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield Ollama(f'http://127.0.0.1:{http.server_port}'), state
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


def test_default_and_custom_endpoint():
    assert selected({})['url'] == DEFAULT_URL
    assert endpoint_url('https://models.example:443/') == 'https://models.example:443'
    assert endpoint_url('http://192.168.1.2:11434') == 'http://192.168.1.2:11434'


@pytest.mark.parametrize('url', ['ftp://example.org', 'http://user:secret@example.org', 'http://a/path',
                                      'http://a?secret=x', 'http://a#x', 'http://a:99999', ' http://a',
                                      'http://a\\evil', 'http://', '', None])
def test_invalid_endpoint(url):
    with pytest.raises(ValueError):
        endpoint_url(url)


def test_discovery_and_refresh_are_live_and_never_generate(server):
    provider, state = server
    assert provider.connection() == 'test-1'
    assert provider.models() == [{'id': 'installed:latest', 'title': 'installed:latest', 'bytes': 42}]
    state['models'] = [{'name': 'new-model'}]
    assert provider.models()[0]['id'] == 'new-model'
    state['models'] = []
    assert provider.models() == []
    assert state['calls'] == ['/api/version', '/api/tags', '/api/tags', '/api/tags']


def test_missing_model_does_not_generate(server):
    provider, state = server
    with pytest.raises(ValueError, match='отсутствует'):
        provider.verify('removed')
    assert state['calls'] == ['/api/tags']


def test_generation_and_audit_have_no_prompt_or_response(server, tmp_path, monkeypatch):
    provider, state = server
    events = tmp_path / 'events.jsonl'
    monkeypatch.setenv('VIDEO_DESCRIPTOR_EVENTS', str(events))
    provider.verify('installed:latest')
    assert state['calls'] == ['/api/tags', '/api/generate']
    assert state['body']['stream'] is False
    log = [json.loads(line) for line in events.read_text().splitlines()]
    verification = [event for event in log if event['action'] == 'llm_verification']
    assert [e['status'] for e in verification] == ['started', 'done']
    assert len({e['operation_id'] for e in verification}) == 1
    assert all('prompt' not in e and 'response' not in e for e in log)


@pytest.mark.parametrize('response', [{'done': True, 'response': ''}, {'done': False, 'response': 'partial'}, {'error': 'private details'}])
def test_generation_failure(server, response):
    provider, state = server
    state['generation'] = response
    with pytest.raises(ValueError):
        provider.verify('installed:latest')


@pytest.mark.parametrize('error,match', [(requests.ConnectionError('secret'), 'подключения'), (requests.Timeout('secret'), 'время')])
def test_connection_refused_and_timeout(monkeypatch, error, match):
    monkeypatch.setattr(requests.Session, 'get', Mock(side_effect=error))
    with pytest.raises(ValueError, match=match):
        Ollama(DEFAULT_URL).connection()


@pytest.mark.parametrize('response', [[], {}, {'models': 'bad'}, {'models': [{}]}, {'models': [{'name': ''}]}])
def test_invalid_inventory(monkeypatch, response):
    result = Mock()
    result.json.return_value = response
    monkeypatch.setattr(requests.Session, 'get', Mock(return_value=result))
    with pytest.raises(ValueError):
        Ollama(DEFAULT_URL).models()


def test_model_does_not_need_to_be_preloaded(server):
    provider, state = server
    require_model(provider, 'installed:latest')
    assert state['calls'] == ['/api/tags']  # No /api/ps or inference requirement.


def test_runtime_and_download_ownership_removed():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'windows-app/component_manager.py').read_text(encoding='utf-8')
    for forbidden in ('def ensure_ollama', 'def start_existing_ollama', '/api/pull', 'OLLAMA_MODELS', '11435', "'ollama_mode'"):
        assert forbidden not in source
    manifest = json.loads((root / 'windows-app/component-manifest.json').read_text())
    assert 'ollama' not in manifest and 'ollama_models' not in manifest
