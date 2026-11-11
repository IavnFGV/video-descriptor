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
    monkeypatch.setattr(postprocess, 'run_process', lambda folder, command, **kw: calls.append(command) or Mock(returncode=0))
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

    monkeypatch.setattr(postprocess, 'run_process', lambda folder, command, **kwargs: run(command, **kwargs))
    jobs.run_job(root, root / 'output/jobs' / job['id'], job)
    assert job['status'] == 'error' and job['stage'] == 'translation'
    assert (folder / 'notes.md').read_text() == 'Completed notes'


def test_unsafe_requests_and_empty_speech_do_not_publish_jobs(recording):
    root, source = recording
    for name, task, url in [('../escape', 'notes', 'http://127.0.0.1:11434'),
                            ('source', 'unexpected', 'http://127.0.0.1:11434'),
                            ('source', 'translate', 'https://user:secret@remote.invalid')]:
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


def test_selected_cloud_model_is_pinned_and_optional_translation_uses_google(recording, monkeypatch):
    from video_descriptor import construction
    root, _ = recording
    monkeypatch.setattr(construction, 'credentials', lambda root: {'api_key': 'private', 'billing_mode': 'paid'})
    config = {'provider': 'gemini', 'model': 'gemini-chosen', 'context_tokens': 16384, 'output_tokens': 2048}
    job = postprocess.enqueue(root, 'source', 'notes', 'gemini-chosen', 'http://127.0.0.1:11434', construction=config)
    assert job['construction']['provider'] == 'gemini'
    assert job['construction']['model'] == job['translation_model'] == 'gemini-chosen'
    assert 'private' not in str(job)
    commands = []
    monkeypatch.setattr(postprocess, 'run_process', lambda folder, command, **kw: commands.append(command) or Mock(returncode=0))
    jobs.run_job(root, root / 'output/jobs' / job['id'], job)
    assert commands[-1][commands[-1].index('--gemini-model') + 1] == 'gemini-chosen'
    assert '--local-model' not in commands[-1]


def test_notes_only_does_not_start_translation(recording, monkeypatch):
    root, _ = recording
    job = postprocess.enqueue(root, 'source', 'notes', 'writer:9b', 'http://127.0.0.1:11434',
                              construction={'provider': 'ollama', 'model': 'writer:9b'}, translate_after=False)
    commands = []
    monkeypatch.setattr(postprocess, 'run_process', lambda folder, command, **kw: commands.append(command) or Mock(returncode=0))
    jobs.run_job(root, root / 'output/jobs' / job['id'], job)
    assert [command[3] for command in commands] == ['video_descriptor.construction']
    assert job['status'] == 'done' and job['stage'] == 'done'


def test_native_cloud_choice_requires_confirmation_without_contacting_ollama(recording, monkeypatch):
    import setup_service

    from video_descriptor import construction
    root, _ = recording
    spec = importlib.util.spec_from_file_location('cloud_notes_app', Path(__file__).resolve().parents[1] / 'windows-app/app.py')
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    monkeypatch.setattr(setup_service.SetupService, 'bootstrap', lambda self: None)
    monkeypatch.setattr(setup_service, 'ollama_status', Mock(side_effect=AssertionError('Ollama must not be contacted')))
    monkeypatch.setattr(setup_service, 'validate_ollama_model', Mock(side_effect=AssertionError('No local model validation')))
    monkeypatch.setattr(construction, 'credentials', lambda root: {'api_key': 'test-private', 'billing_mode': 'paid'})
    start = Mock()
    monkeypatch.setattr(jobs, 'start_worker', start)
    value = {'workspace': str(root), 'npu_worker_directory': str(root / 'benchmark'), 'ollama_url': 'http://127.0.0.1:11434'}
    with ThreadingHTTPServer(('127.0.0.1', 0), app.make_handler(value, 'instance')) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}/api/native/postprocess'
        body = {'folder': 'source', 'task': 'notes', 'translate_after': False,
                'construction': {'provider': 'gemini', 'model': 'gemini-selected'}}
        headers = {'X-App-Instance': 'instance'}
        try:
            assert requests.post(url, json=body, headers=headers, timeout=5).status_code == 400
            start.assert_not_called()
            response = requests.post(url, json={**body, 'cloud_confirmed': True}, headers=headers, timeout=5)
            assert response.status_code == 202, response.text
            assert response.json()['construction']['model'] == 'gemini-selected'
            assert 'test-private' not in response.text
            assert not response.json()['translate_after']
            start.assert_called_once()
        finally:
            server.shutdown()
            thread.join()


def test_native_lmstudio_queues_without_ollama_and_pins_worker(recording, monkeypatch):
    import setup_service

    from video_descriptor import lmstudio, translation_settings
    root, _ = recording
    translation_settings.save(root, {'provider': 'lmstudio', 'lmstudio_model': 'local/model',
                                    'lmstudio_url': 'http://127.0.0.1:1234/v1'})
    spec = importlib.util.spec_from_file_location('lmstudio_app', Path(__file__).resolve().parents[1] / 'windows-app/app.py')
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    monkeypatch.setattr(setup_service.SetupService, 'bootstrap', lambda self: None)
    monkeypatch.setattr(setup_service, 'ollama_status', Mock(side_effect=AssertionError('Must not contact Ollama')))
    monkeypatch.setattr(setup_service, 'validate_ollama_model', Mock(side_effect=AssertionError('Must not validate Ollama')))
    monkeypatch.setattr(lmstudio, 'models', lambda _: [{'id': 'local/model'}])
    monkeypatch.setattr(jobs, 'start_worker', lambda _: None)
    value = {'workspace': str(root), 'npu_worker_directory': str(root / 'benchmark'),
             'ollama_url': 'http://127.0.0.1:11434'}
    with ThreadingHTTPServer(('127.0.0.1', 0), app.make_handler(value, 'instance')) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            response = requests.post(f'http://127.0.0.1:{server.server_port}/api/native/postprocess',
                                     json={'folder': 'source', 'task': 'translate'},
                                     headers={'X-App-Instance': 'instance'}, timeout=5)
            assert response.status_code == 202, response.text
            job = response.json()
            assert job['translation_provider'] == 'lmstudio'
            assert job['translation_model'] == 'local/model'
            assert job['translation_base_url'] == 'http://127.0.0.1:1234/v1'
            commands = []
            def run_process(folder, command, **kwargs):
                commands.append((command, kwargs['env']))
                return Mock(returncode=0)
            monkeypatch.setattr(postprocess, 'run_process', run_process)
            postprocess.run(root, jobs.jobs_dir(root) / job['id'], job, None)
            command, env = commands[0]
            assert command[command.index('--lmstudio-model') + 1] == 'local/model'
            assert command[command.index('--lmstudio-url') + 1] == job['translation_base_url']
            assert env['VIDEO_DESCRIPTOR_JOB_LMSTUDIO_URL'] == job['translation_base_url']
        finally:
            server.shutdown()
            thread.join()



def test_notes_failure_exposes_structured_reason_and_preserves_source(recording, monkeypatch):
    root, source = recording
    original = (source/'speech.json').read_bytes()
    job = postprocess.enqueue(root,'source','notes','qwen:9b','http://127.0.0.1:11434')
    result = root/'output'/job['folder']
    jobs.write_json(result/'construction-error.json', {'error':'Нужны заголовки с таймкодами'})
    monkeypatch.setattr(postprocess,'run_process',lambda *a,**kw: Mock(returncode=1))
    jobs.run_job(root, root/'output/jobs'/job['id'],job)
    assert 'Нужны заголовки с таймкодами' in job['error']
    assert (source/'speech.json').read_bytes() == original
