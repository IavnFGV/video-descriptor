"""External HTTP contract, live inventories and generation; no user services involved."""
import importlib
import importlib.util
import json
import shutil
import subprocess
import threading
import time
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
    state = {'models': [{'name': 'installed:latest', 'size': 42}], 'capabilities': ['completion'],
             'generation': {'done': True, 'response': 'ready'}, 'calls': [], 'bodies': [],
             'responses': {}, 'wait': {}, 'entered': {path: threading.Event() for path in
                 ('/api/version', '/api/tags', '/api/show', '/api/generate')}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, value, code=200):
            state['calls'].append(self.path)
            if self.path in state['entered']:
                state['entered'][self.path].set()
            gate = state['wait'].get(self.path)
            if gate is not None:
                gate.wait(3)  # Bounded fixture teardown even if a regression fails a test.
            code, value = state['responses'].get(self.path, (code, value))
            data = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # Expected when a timeout test closes the client socket.

        def do_GET(self):
            if self.path == '/api/version':
                return self.reply({'version': 'test-1'})
            if self.path == '/api/tags':
                return self.reply({'models': state['models']})
            self.reply({'error': 'unknown endpoint'}, 404)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['body'] = body
            state['bodies'].append((self.path, body))
            if self.path not in {'/api/show', '/api/generate'}:
                return self.reply({'error': 'unsupported endpoint'}, 404)
            if body.get('model') not in {m['name'] for m in state['models']}:
                return self.reply({'error': 'model not found'}, 404)
            if self.path == '/api/show':
                return self.reply({'capabilities': state['capabilities'], 'model_info': {'test.context_length': 4096}})
            if 'completion' not in state['capabilities']:
                return self.reply({'error': 'does not support generation'}, 400)
            if body.get('stream') is not False or not body.get('prompt'):
                return self.reply({'error': 'expected non-streaming generation prompt'}, 400)
            self.reply(state['generation'])

    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    try:
        yield Ollama(f'http://127.0.0.1:{http.server_port}'), state
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


@pytest.fixture
def native(server, tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('ollama_polish_native', root / 'windows-app/app.py')
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    here = tmp_path / 'app'
    here.mkdir()
    monkeypatch.setattr(app, 'HERE', here)
    setup = importlib.import_module('setup_service')
    monkeypatch.setattr(setup.SetupService, 'bootstrap', lambda self: None)
    monkeypatch.setenv('VIDEO_DESCRIPTOR_EVENTS', str(tmp_path / 'events.jsonl'))
    provider, state = server
    value = {'workspace': str(tmp_path / 'workspace'), 'npu_worker_directory': str(tmp_path / 'no-workers'),
             'ollama_url': provider.endpoint, 'ai_components_directory': str(tmp_path / 'components')}
    with ThreadingHTTPServer(('127.0.0.1', 0), app.make_handler(value, 'test-instance')) as http:
        thread = threading.Thread(target=http.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{http.server_port}'
        try:
            yield base, value, state
        finally:
            for gate in state['wait'].values():
                gate.set()
            http.shutdown()
            thread.join()


def post(base, path, body):
    response = requests.post(base + path, json=body, headers={'X-App-Instance': 'test-instance'}, timeout=2)
    response.raise_for_status()
    return response.json()


def wait_for_component(base):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        snapshot = requests.get(base + '/api/components', timeout=1).json()
        if not snapshot['active']:
            return next(item for item in snapshot['components'] if item['id'] == 'ollama')
        time.sleep(.01)
    raise AssertionError('Verification did not finish')


def test_settings_connect_refresh_and_selection_never_generate(native):
    base, value, state = native
    for _ in range(2):
        response = requests.get(base + '/api/setup/ollama', timeout=2)
        assert response.status_code == 200 and response.json()['models']
    post(base, '/api/setup/ollama', {'endpoint': value['ollama_url']})
    post(base, '/api/setup/ollama', {'model': 'installed:latest'})
    assert '/api/show' in state['calls']
    assert '/api/generate' not in state['calls']
    post(base, '/api/components', {'component': 'ollama', 'action': 'check', 'model': 'installed:latest'})
    assert wait_for_component(base)['state'] == 'ready'
    assert state['calls'].count('/api/generate') == 1


def test_slow_verification_keeps_http_ui_responsive_and_cancellation_truthful(native, tmp_path):
    base, value, state = native
    release = state['wait']['/api/generate'] = threading.Event()
    post(base, '/api/components', {'component': 'ollama', 'action': 'check', 'model': 'installed:latest'})
    assert state['entered']['/api/generate'].wait(2)
    # The background inference must not hold the HTTP handler or manager lock.
    assert requests.get(base + '/health', timeout=1).status_code == 200
    snapshot = requests.get(base + '/api/components', timeout=1).json()
    assert snapshot['active'] == 'ollama'
    post(base, '/api/components', {'component': 'ollama', 'action': 'cancel'})
    snapshot = requests.get(base + '/api/components', timeout=1).json()
    item = next(item for item in snapshot['components'] if item['id'] == 'ollama')
    assert item['cancel_requested'] and 'Ждём завершения' in item['message']
    assert snapshot['active'] == 'ollama'  # No claim that remote inference has stopped.
    release.set()
    item = wait_for_component(base)
    assert item['state'] == 'error' and 'Остановлено' in item['message']
    events = [json.loads(line) for line in (tmp_path / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
    verification = [event for event in events if event['action'] == 'llm_verification']
    assert [event['status'] for event in verification] == ['started', 'error']
    assert not (Path(value['workspace']) / '.devcontainer/translation-settings.json').exists()


def test_cancel_during_metadata_prevents_generation(server):
    provider, state = server

    def check_cancel():
        if '/api/show' in state['calls']:
            raise RuntimeError('Cancelled')

    with pytest.raises(RuntimeError, match='Cancelled'):
        provider.verify('installed:latest', check_cancel=check_cancel)
    assert state['calls'] == ['/api/tags', '/api/show']


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


def test_text_capabilities_are_checked_without_generation(server):
    provider, state = server
    provider.validate_text_model('installed:latest')
    assert state['calls'] == ['/api/show']
    assert state['body'] == {'model': 'installed:latest'}


def test_embedding_only_model_never_reaches_generation(server):
    provider, state = server
    state['capabilities'] = ['embedding']
    with pytest.raises(ValueError, match='не поддерживает генерацию'):
        provider.verify('installed:latest')
    assert state['calls'] == ['/api/tags', '/api/show']


@pytest.mark.parametrize('path', ['/api/show', '/api/generate'])
def test_model_removed_between_discovery_and_request(server, path):
    provider, state = server
    state['responses'][path] = (404, {'error': 'model not found: private model name'})
    with pytest.raises(ValueError, match='Модель отсутствует') as error:
        provider.verify('installed:latest')
    assert 'private' not in str(error.value)
    if path == '/api/show':
        assert '/api/generate' not in state['calls']


@pytest.mark.parametrize('path,value', [
    ('/api/version', b'not-json'), ('/api/version', {}), ('/api/version', {'version': 1}),
    ('/api/tags', b'{'), ('/api/tags', {'models': None}),
    ('/api/tags', {'models': [{'name': None}]}),
    ('/api/show', []), ('/api/show', {}), ('/api/show', {'capabilities': 'completion'}),
    ('/api/show', {'capabilities': [None]}), ('/api/generate', b'not-json'),
])
def test_malformed_http_responses(server, path, value):
    provider, state = server
    state['responses'][path] = (200, value)
    action = provider.connection if path == '/api/version' else provider.models if path == '/api/tags' else lambda: provider.verify('installed:latest')
    with pytest.raises(ValueError) as error:
        action()
    assert 'подключения' not in str(error.value)
    if path == '/api/show':
        assert '/api/generate' not in state['calls']


def test_generation_http_failure_does_not_look_like_connection_refusal(server):
    provider, state = server
    state['responses']['/api/generate'] = (500, {'error': 'PRIVATE runner details'})
    with pytest.raises(ValueError, match='не выполнила генерацию') as error:
        provider.verify('installed:latest')
    assert 'PRIVATE' not in str(error.value)


@pytest.mark.parametrize('path', ['/api/version', '/api/generate'])
def test_real_http_timeouts(server, path):
    provider, state = server
    release = state['wait'][path] = threading.Event()
    try:
        body = {'model': 'installed:latest', 'prompt': 'Test', 'stream': False} if path == '/api/generate' else None
        with pytest.raises(ValueError, match='время ожидания') as error:
            provider.request(path, body, timeout=.05)
        assert state['entered'][path].is_set()
        assert ('генерации' in str(error.value)) == (path == '/api/generate')
    finally:
        release.set()


def test_verification_timeout_keeps_generation_bound_and_reports_failure(server, monkeypatch):
    provider, state = server
    request = provider.request
    timeouts = []

    def bounded(path, body=None, timeout=5):
        if path == '/api/generate':
            timeouts.append(timeout)
            raise ValueError('Истекло время ожидания генерации Ollama')
        return request(path, body, timeout)

    monkeypatch.setattr(provider, 'request', bounded)
    with pytest.raises(ValueError, match='время ожидания генерации'):
        provider.verify('installed:latest')
    assert timeouts == [180]
    assert state['calls'] == ['/api/tags', '/api/show']


def test_discovery_capabilities_and_verification_never_start_or_download(server, monkeypatch):
    provider, state = server
    monkeypatch.setattr(subprocess, 'Popen', Mock(side_effect=AssertionError('Ollama process startup')))
    provider.connection()
    provider.models()
    provider.validate_text_model('installed:latest')
    provider.verify('installed:latest')
    assert set(state['calls']) == {'/api/version', '/api/tags', '/api/show', '/api/generate'}
    assert state['calls'].count('/api/generate') == 1
    subprocess.Popen.assert_not_called()


def test_generation_and_audit_have_no_prompt_or_response(server, tmp_path, monkeypatch):
    provider, state = server
    events = tmp_path / 'events.jsonl'
    monkeypatch.setenv('VIDEO_DESCRIPTOR_EVENTS', str(events))
    provider.verify('installed:latest')
    assert state['calls'] == ['/api/tags', '/api/show', '/api/generate']
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


def test_installed_acceptance_connects_external_server_without_legacy_mode(native, tmp_path):
    spec = importlib.util.spec_from_file_location('external_installed_acceptance',
        Path(__file__).resolve().parents[1] / 'windows-app/sandbox/acceptance_api.py')
    acceptance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(acceptance)
    base, value, state = native
    client = acceptance.InstalledAPI.__new__(acceptance.InstalledAPI)
    client.origin, client.instance = base, 'test-instance'
    client.settings = {'ollama_url': 'http://127.0.0.1:1'}
    client.connect = lambda: None  # The native HTTP fixture has no packaged installation identity.
    transition = client.connect_ollama(value['ollama_url'])
    assert transition['before'] == 'http://127.0.0.1:1'
    assert transition['after'] == value['ollama_url']
    assert transition['ownership'] == 'external' and 'mode' not in transition
    assert client.settings['ollama_url'] == value['ollama_url']
    assert '/api/generate' not in state['calls']
    client.ollama_model, client.reports = 'installed:latest', tmp_path
    state['models'][0]['digest'] = 'fixture-digest'
    assert client.run('ollama-model')['status'] == 'PASS'
    settings = requests.get(base + '/api/translation-settings', timeout=2).json()
    assert settings['provider'] == 'ollama' and settings['ollama_model'] == 'installed:latest'


def test_installed_acceptance_reports_connection_failure_without_changing_endpoint(native):
    spec = importlib.util.spec_from_file_location('failed_installed_acceptance',
        Path(__file__).resolve().parents[1] / 'windows-app/sandbox/acceptance_api.py')
    acceptance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(acceptance)
    base, value, state = native
    client = acceptance.InstalledAPI.__new__(acceptance.InstalledAPI)
    client.origin, client.instance = base, 'test-instance'
    client.settings = {'ollama_url': 'http://127.0.0.1:1'}
    client.connect = lambda: None
    state['responses']['/api/version'] = (503, {'error': 'fixture unavailable'})
    with pytest.raises(RuntimeError):
        client.connect_ollama(value['ollama_url'])
    assert client.settings['ollama_url'] == 'http://127.0.0.1:1'
