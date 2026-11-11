"""Connection ownership and endpoint regression contracts; no real user service touched."""
import importlib
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

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
    from video_descriptor.ollama_provider import Ollama
    def request(self, endpoint, body=None, timeout=5):
        calls.append((self.endpoint, endpoint, body))
        return {'version': 'test'} if endpoint == '/api/version' else {'models': [{'name': 'existing:4b', 'size': 123}]}
    monkeypatch.setattr(Ollama, 'request', request)


@pytest.mark.parametrize('action', ['install', 'pull', 'prepare', 'remove', 'start_existing'])
def test_removed_lifecycle_actions_cannot_download_launch_or_delete(manager, action):
    user_data = manager.root / 'user-models'
    user_data.mkdir()
    with pytest.raises(ValueError):
        manager.action('ollama', {'action': action, 'confirmed': True})
    assert user_data.is_dir()
    manager.download.assert_not_called()
    cm.subprocess.Popen.assert_not_called()


def test_endpoint_change_clears_both_selections_without_implicit_replacement(manager, monkeypatch):
    from video_descriptor import translation_settings
    mock_service(monkeypatch, [])
    root = manager.manager.value['workspace']
    translation_settings.save(root, {'provider': 'ollama', 'ollama_model': 'existing:4b'})
    notes = Path(root) / '.devcontainer/notes-settings.json'
    notes.write_text('{"ollama_model":"existing:4b"}')
    endpoint = 'https://models.example:11434'
    manager.connect_ollama(endpoint)
    assert translation_settings.load(root)['ollama_model'] == ''
    assert json.loads(notes.read_text())['ollama_model'] == ''
    assert ollama_connection.base_url(root) == endpoint
    saved = json.loads((manager.here / 'config.local.json').read_text(encoding='utf-8'))
    assert saved['ollama_model'] == ''
    manager.close()
    manager.download.assert_not_called()
    cm.subprocess.Popen.assert_not_called()


def test_refresh_on_same_endpoint_preserves_saved_selection(manager, monkeypatch):
    from video_descriptor import translation_settings
    mock_service(monkeypatch, [])
    root = manager.manager.value['workspace']
    translation_settings.save(root, {'ollama_model': 'existing:4b'})
    manager.connect_ollama(ollama_connection.DEFAULT_URL)
    assert translation_settings.load(root)['ollama_model'] == 'existing:4b'


def test_context_check_uses_selected_endpoint_not_stale_environment(manager, monkeypatch):
    mock_service(monkeypatch, [])
    endpoint = 'http://127.0.0.1:12439'
    manager.connect_ollama(endpoint)
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


def test_failed_connection_commit_retains_previous_endpoint_and_both_files(manager, monkeypatch):
    mock_service(monkeypatch, [])
    manager.connect_ollama(ollama_connection.DEFAULT_URL)
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
        manager.connect_ollama('http://127.0.0.1:12439')
    assert manager.manager.value['ollama_url'] == ollama_connection.DEFAULT_URL
    assert (config.read_bytes(), workspace.read_bytes()) == before
