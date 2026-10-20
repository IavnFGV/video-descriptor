"""Connection ownership and endpoint regression contracts; no real user service touched."""
import importlib
import json
import socket
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from video_descriptor import construction, jobs, ollama_connection, postprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows-app'))
cm = importlib.import_module('component_manager')


@pytest.fixture
def manager(tmp_path, monkeypatch):
    here = tmp_path / 'windows-app'
    here.mkdir()
    (here / 'component-manifest.json').write_text('{}')
    backend = SimpleNamespace(_lock=threading.RLock(), operation=None, model=tmp_path / 'whisper',
                              value={'workspace': str(tmp_path / 'workspace'), 'ollama_url': ollama_connection.DEFAULT_URL}, here=here)
    instance = cm.ComponentManager(SimpleNamespace(manager=backend, here=here, guard=lambda: None), tmp_path / 'components')
    monkeypatch.setattr(instance, 'download', Mock(side_effect=AssertionError('Unexpected binary download')))
    monkeypatch.setattr(cm.subprocess, 'Popen', Mock(side_effect=AssertionError('Unexpected second server')))
    return instance


def mock_service(monkeypatch, calls):
    setup = importlib.import_module('setup_service')
    def request(value, endpoint, body=None):
        calls.append((value['ollama_url'], endpoint, body))
        return {'version': 'existing-1.0'} if endpoint == '/api/version' else {'models': [{'name': 'existing:4b', 'size': 123, 'digest': 'preserve'}]}
    monkeypatch.setattr(setup, 'ollama_request', request)


def test_running_existing_is_preferred_without_download_process_or_model_directory(manager, monkeypatch):
    calls = []
    mock_service(monkeypatch, calls)
    proof = manager.connect_ollama('existing')
    assert proof['models'][0]['name'] == 'existing:4b'
    assert {url for url, _, _ in calls} == {ollama_connection.DEFAULT_URL}
    assert {endpoint for _, endpoint, _ in calls} == {'/api/version', '/api/tags'}
    assert manager.manager.value['ollama_mode'] == 'existing'
    manager.ensure_ollama()
    manager.download.assert_not_called()
    cm.subprocess.Popen.assert_not_called()
    assert not (manager.root / 'ollama-models').exists()


@pytest.mark.parametrize('mode', ['existing', 'service'])
def test_unavailable_external_check_or_pull_never_starts_or_switches(manager, monkeypatch, mode):
    endpoint = 'http://127.0.0.1:11434' if mode == 'existing' else 'http://127.0.0.1:12439'
    manager.manager.value.update(ollama_url=endpoint, ollama_mode=mode)
    monkeypatch.setattr(manager, 'inspect_ollama', Mock(side_effect=requests.ConnectionError()))
    monkeypatch.setattr(manager, 'existing_executable', lambda: 'C:/Programs/Ollama/ollama.exe')
    for action in ['check', 'pull']:
        with pytest.raises(ValueError):
            manager.ollama({'model': 'existing:4b'}, action)
        assert manager.manager.value['ollama_url'] == endpoint
        assert manager.manager.value['ollama_mode'] == mode
    cm.subprocess.Popen.assert_not_called()
    manager.download.assert_not_called()


def test_absent_ollama_requires_explicit_managed_mode_and_confirmation(manager, monkeypatch):
    monkeypatch.setattr(manager, 'inspect_ollama', Mock(side_effect=requests.ConnectionError()))
    monkeypatch.setattr(manager, 'existing_executable', lambda: None)
    with pytest.raises(ValueError, match='Подтвердите'):
        manager.action('ollama', {'action': 'install', 'mode': 'managed'})
    with pytest.raises(ValueError, match='режим'):
        manager.action('ollama', {'action': 'install', 'confirmed': True})
    with pytest.raises(ValueError, match='недоступен'):
        manager.ensure_ollama()
    manager.download.assert_not_called()
    cm.subprocess.Popen.assert_not_called()


def test_restart_retains_external_endpoint_and_selected_models(manager, monkeypatch):
    calls = []
    mock_service(monkeypatch, calls)
    endpoint = 'http://127.0.0.1:12439'
    manager.connect_ollama('service', endpoint)
    settings = Path(manager.manager.value['workspace']) / '.devcontainer/notes-settings.json'
    settings.write_text('{"ollama_model":"existing:4b"}')
    saved = json.loads((manager.here / 'config.local.json').read_text(encoding='utf-8'))
    assert saved['ollama_url'] == endpoint
    backend = SimpleNamespace(**{**vars(manager.manager), 'value': {**manager.manager.value, **saved}})
    restored = cm.ComponentManager(SimpleNamespace(manager=backend, here=manager.here, guard=lambda: None), manager.root)
    assert restored.snapshot()['ollama_connection']['mode'] == 'service'
    assert restored.manager.value['ollama_url'] == endpoint
    assert json.loads(settings.read_text())['ollama_model'] == 'existing:4b'
    cm.subprocess.Popen.assert_not_called()


def test_close_and_mode_switch_do_not_stop_external_or_move_models(manager, monkeypatch, tmp_path):
    mock_service(monkeypatch, [])
    user_models = tmp_path / 'user-models'
    user_models.mkdir()
    model = user_models / 'owned-by-user.bin'
    model.write_bytes(b'never move or delete')
    manager.connect_ollama('existing')
    manager.connect_ollama('service', 'http://127.0.0.1:12439')
    manager.close()
    assert model.read_bytes() == b'never move or delete'
    assert manager.server is None
    cm.subprocess.Popen.assert_not_called()


def test_only_owned_managed_process_is_stopped_on_close(manager):
    process = Mock()
    process.poll.return_value = None
    manager.server = process
    manager.close()
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=15)


def test_context_check_uses_selected_endpoint_not_stale_environment(manager, monkeypatch):
    mock_service(monkeypatch, [])
    endpoint = 'http://127.0.0.1:12439'
    manager.connect_ollama('service', endpoint)
    monkeypatch.setenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11435')
    monkeypatch.delenv('VIDEO_DESCRIPTOR_JOB_OLLAMA_URL', raising=False)
    calls = []
    response = Mock()
    response.json.return_value = {'model_info': {'test.context_length': 4096}}
    monkeypatch.setattr(construction.requests, 'post', lambda url, **kwargs: calls.append(url) or response)
    config = construction.validate({'provider': 'ollama', 'model': 'existing:4b', 'context_tokens': 8192, 'output_tokens': 512})
    result = construction.actual_limits(manager.manager.value['workspace'], config)
    assert result['context_tokens'] == 4096
    assert calls == [endpoint + '/api/show']


def test_translation_and_notes_children_share_immutable_endpoint_even_after_switch(tmp_path, monkeypatch):
    source = tmp_path / 'output/source'
    source.mkdir(parents=True)
    jobs.write_json(source / 'manifest.json', {'video': str(tmp_path / 'data/sample.mp4')})
    jobs.write_json(source / 'speech.json', {'status': 'done', 'segments': [{'id': 's1', 'start': 0, 'end': 1, 'text': 'Sample', 'speaker': 'unknown'}], 'duration': 1})
    endpoint = 'http://127.0.0.1:12439'
    job = postprocess.enqueue(tmp_path, 'source', 'notes', 'existing:4b', endpoint)
    monkeypatch.setenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11435')
    calls = []
    monkeypatch.setattr(postprocess, 'run_process', lambda folder, command, **kwargs: calls.append((command, kwargs['env'])) or Mock(returncode=0))
    jobs.run_job(tmp_path, tmp_path / 'output/jobs' / job['id'], job)
    assert job['status'] == 'done'
    assert len(calls) == 2
    assert all(env['OLLAMA_BASE_URL'] == endpoint and env['VIDEO_DESCRIPTOR_JOB_OLLAMA_URL'] == endpoint for _, env in calls)
    assert calls[-1][0][calls[-1][0].index('--base-url') + 1] == endpoint


@pytest.mark.parametrize('url', ['https://example.com', 'http://192.168.1.2:11434', 'http://localhost@evil.test', 'http://127.0.0.1/path', 'http://127.0.0.1?key=secret', 'http://127.0.0.1:99999', ' http://127.0.0.1', 'http://127.0.0.1\\evil'])
def test_mvp_rejects_unsafe_endpoints(url):
    with pytest.raises(ValueError):
        ollama_connection.loopback_url(url)



def test_existing_executable_launch_requires_explicit_action_and_keeps_user_model_directory(manager, monkeypatch, tmp_path):
    executable = tmp_path / 'Ollama/ollama.exe'
    executable.parent.mkdir()
    executable.write_bytes(b'test fixture')
    monkeypatch.setattr(manager, 'existing_executable', lambda: str(executable))
    monkeypatch.setattr(manager, 'verify_signature', lambda path: 'Valid')
    calls = []
    def inspect(url):
        calls.append(url)
        if len(calls) == 1:
            raise requests.ConnectionError()
        return {'version': '1'}, [{'name': 'user:4b'}]
    monkeypatch.setattr(manager, 'inspect_ollama', inspect)
    import socket
    socket_mock = Mock()
    socket_mock.__enter__ = Mock(return_value=socket_mock)
    socket_mock.__exit__ = Mock(return_value=False)
    socket_mock.connect_ex.return_value = 1
    monkeypatch.setattr(socket, 'socket', lambda: socket_mock)
    monkeypatch.setenv('OLLAMA_MODELS', str(tmp_path / 'user-models'))
    process = Mock()
    spawn = Mock(return_value=process)
    monkeypatch.setattr(cm.subprocess, 'Popen', spawn)
    manager.start_existing_ollama()
    args, kwargs = spawn.call_args
    assert args[0] == [str(executable), 'serve']
    assert kwargs['env']['OLLAMA_HOST'] == '127.0.0.1:11434'
    assert kwargs['env']['OLLAMA_MODELS'] == str(tmp_path / 'user-models')
    assert manager.manager.value['ollama_mode'] == 'existing'
    manager.close()
    process.terminate.assert_not_called()


def test_managed_install_uses_only_owned_binary_after_explicit_consent(manager, monkeypatch):
    profile = {'version': '1.0'}
    manager.manifest['ollama'] = profile
    target = manager.root / 'ollama-1.0'
    target.mkdir()
    (target / 'ollama.exe').write_bytes(b'managed test binary')
    (target / '.managed.json').write_text('{"component":"ollama"}')
    monkeypatch.setattr(manager, 'inspect_ollama', lambda url: ({'version': '1.0'}, []))
    process = Mock()
    process.poll.return_value = None
    spawn = Mock(return_value=process)
    monkeypatch.setattr(cm.subprocess, 'Popen', spawn)
    monkeypatch.setattr(socket.socket, 'connect_ex', lambda self, address: 1)
    manager.action('ollama', {'action': 'install', 'mode': 'managed', 'confirmed': True})
    deadline = time.monotonic() + 5
    while manager.active and time.monotonic() < deadline:
        time.sleep(.01)
    assert manager.active is None
    assert manager.components['ollama']['state'] == 'installed'
    assert manager.manager.value['ollama_mode'] == 'managed'
    assert spawn.call_args.args[0] == [str(target / 'ollama.exe'), 'serve']
    assert spawn.call_args.kwargs['env']['OLLAMA_MODELS'] == str(manager.root / 'ollama-models')
    assert manager.server is process
    manager.close()
    process.terminate.assert_called_once()



def test_failed_connection_commit_retains_previous_endpoint_and_both_files(manager, monkeypatch):
    mock_service(monkeypatch, [])
    manager.connect_ollama('existing')
    config = manager.here / 'config.local.json'
    workspace = ollama_connection.workspace_file(manager.manager.value['workspace'])
    before = config.read_bytes(), workspace.read_bytes()
    original_atomic = cm.atomic
    def fail(path, data):
        if path == workspace:
            raise PermissionError('test failure')
        original_atomic(path, data)
    monkeypatch.setattr(cm, 'atomic', fail)
    with pytest.raises(PermissionError):
        manager.connect_ollama('service', 'http://127.0.0.1:12439')
    assert manager.manager.value['ollama_url'] == ollama_connection.DEFAULT_URL
    assert (config.read_bytes(), workspace.read_bytes()) == before
