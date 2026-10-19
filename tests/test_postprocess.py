import importlib.util
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from video_descriptor import jobs, postprocess, speech


@pytest.fixture
def recording(tmp_path):
    source = tmp_path / 'output/source'
    source.mkdir(parents=True)
    rows = [{'id': 's1', 'start': 0, 'end': 5, 'text': 'Original', 'speaker': 'unknown'}]
    jobs.write_json(source / 'manifest.json', {'video': str(tmp_path / 'data/sample.mp4')})
    jobs.write_json(source / 'speech.json', {'status': 'done', 'segments': rows, 'duration': 5})
    jobs.write_json(source / 'transcript-edits.json', {'segments': [{**rows[0], 'text': 'Corrected'}],
                                                     'translations': {'s1': 'Старый перевод'}})
    return tmp_path, source


@pytest.mark.parametrize('task', ['translate', 'notes'])
def test_new_version_captures_edits_and_model_and_never_changes_original(recording, task):
    root, source = recording
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    job = postprocess.enqueue(root, 'source', task, 'qwen:9b', 'http://127.0.0.1:11434')
    result = root / 'output' / job['folder']
    assert job['translation_model'] == 'qwen:9b'
    assert jobs.read_json(result / 'transcript.json')[0]['text'] == 'Corrected'
    assert jobs.read_json(result / 'transcript.json')[0]['id'] == 's1'
    assert not (result / 'transcript-edits.json').exists()
    assert not (result / 'translations.json').exists()
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}
    snapshot = speech.state(root, {'job': [job['id']]})
    assert snapshot['job']['status'] == 'queued'
    assert snapshot['result']['segments'][0]['text'] == 'Corrected'
    with pytest.raises(ValueError, match='уже находится'):
        postprocess.enqueue(root, 'source', task, 'qwen:9b', 'http://127.0.0.1:11434')


@pytest.mark.parametrize('task,modules', [('translate', ['video_descriptor.translate']),
                                        ('notes', ['video_descriptor.construction', 'video_descriptor.translate'])])
def test_worker_does_not_repeat_asr_and_uses_pinned_local_model(recording, monkeypatch, task, modules):
    root, _ = recording
    job = postprocess.enqueue(root, 'source', task, 'pinned:9b', 'http://127.0.0.1:11434')
    calls = []
    monkeypatch.setattr(postprocess.subprocess, 'run', lambda command, **kw: calls.append(command) or Mock(returncode=0))
    jobs.run_job(root, root / 'output/jobs' / job['id'], job)
    assert [command[3] for command in calls] == modules
    assert calls[-1][calls[-1].index('--local-model') + 1] == 'pinned:9b'
    assert job['status'] == 'done' and job['stage'] == 'done'


def test_failed_translation_is_retryable_and_preserves_notes(recording, monkeypatch):
    root, _ = recording
    job = postprocess.enqueue(root, 'source', 'notes', 'qwen:9b', 'http://127.0.0.1:11434')
    folder = root / 'output' / job['folder']

    def run(command, **kwargs):
        if command[3] == 'video_descriptor.construction':
            (folder / 'notes.md').write_text('Completed notes')
            return Mock(returncode=0)
        return Mock(returncode=1)

    monkeypatch.setattr(postprocess.subprocess, 'run', run)
    jobs.run_job(root, root / 'output/jobs' / job['id'], job)
    assert job['status'] == 'error' and job['stage'] == 'translation'
    assert (folder / 'notes.md').read_text() == 'Completed notes'


def test_unsafe_requests_and_empty_speech_do_not_publish_jobs(recording):
    root, source = recording
    for name, task, url in [('../escape', 'notes', 'http://127.0.0.1:11434'),
                            ('source', 'unexpected', 'http://127.0.0.1:11434'),
                            ('source', 'translate', 'https://remote.invalid')]:
        with pytest.raises(ValueError):
            postprocess.enqueue(root, name, task, 'qwen:9b', url)
    (source / 'transcript-edits.json').unlink()
    jobs.write_json(source / 'speech.json', {'status': 'done', 'segments': []})
    with pytest.raises(ValueError, match='с речью'):
        postprocess.enqueue(root, 'source', 'translate', 'qwen:9b', 'http://127.0.0.1:11434')
    assert not list((root / 'output/jobs').glob('*/job.json'))


def test_native_postprocess_api_checks_instance_and_origin_then_queues_snapshot(recording, monkeypatch):
    root, _ = recording
    app_path = Path(__file__).resolve().parents[1] / 'windows-app/app.py'
    spec = importlib.util.spec_from_file_location('postprocess_native_app', app_path)
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    import setup_service
    monkeypatch.setattr(setup_service, 'ollama_status', lambda value: {'selected': 'chosen:9b'})
    monkeypatch.setattr(setup_service, 'validate_ollama_model', lambda value, model: None)
    start = Mock()
    monkeypatch.setattr(jobs, 'start_worker', start)
    value = {'workspace': str(root), 'npu_worker_directory': str(root / 'benchmark'),
             'ollama_url': 'http://127.0.0.1:11434'}
    with ThreadingHTTPServer(('127.0.0.1', 0), app.make_handler(value, 'instance')) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}/api/native/postprocess'
        try:
            body = {'folder': 'source', 'task': 'translate', 'model': 'untrusted-choice'}
            assert requests.post(url, json=body, timeout=5).status_code == 403
            assert requests.post(url, json=body, headers={'X-App-Instance': 'instance',
                                  'Origin': 'https://foreign.invalid'}, timeout=5).status_code == 403
            start.assert_not_called()
            response = requests.post(url, json=body, headers={'X-App-Instance': 'instance'}, timeout=5)
            assert response.status_code == 202
            assert response.json()['translation_model'] == 'chosen:9b'
            start.assert_called_once()
        finally:
            server.shutdown()
            thread.join()


def test_notes_and_translation_use_separately_selected_models(recording):
    root, _ = recording
    job = postprocess.enqueue(root, 'source', 'notes', 'translator:9b', 'http://127.0.0.1:11434',
                              notes_model='writer:9b')
    assert job['translation_model'] == 'translator:9b'
    assert job['construction']['model'] == 'writer:9b'
