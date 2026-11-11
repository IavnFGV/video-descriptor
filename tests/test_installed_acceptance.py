"""Result-contract regressions; no mocks are reported as real acceptance."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installed_acceptance_api', ROOT / 'windows-app/sandbox/acceptance_api.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


def speech():
    return {'device': 'CPU', 'duration': 9.14, 'segments': [
        {'id': 's1', 'start': 0.0, 'end': 4.0, 'text': 'The train arrives at nine.'}]}


def test_cpu_inference_requires_real_text_and_bounded_timestamps():
    result = api.validate_speech(speech())
    assert result['device'] == 'CPU' and result['segments'] == 1
    assert result['text'] == 'The train arrives at nine.'


def test_prepare_poll_retries_a_stale_snapshot_instead_of_failing_or_passing():
    state = {'preparing': False, 'error': '', 'capabilities': {'CPU': {'ready': False}}}
    assert not api.preparation_complete(state)
    state['capabilities']['CPU']['ready'] = True
    assert api.preparation_complete(state)
    state['preparing'] = True
    assert not api.preparation_complete(state)
    state['preparing'] = False
    state['capabilities']['CPU']['ready'] = False
    state['error'] = 'Actual worker failure'
    assert api.preparation_complete(state)  # caller records the error as FAIL


@pytest.mark.parametrize('field,value', [('device', 'GPU'), ('segments', [])])
def test_wrong_device_and_empty_results_are_not_pass(field, value):
    result = speech()
    result[field] = value
    with pytest.raises(ValueError):
        api.validate_speech(result)


@pytest.mark.parametrize('row', [
    {'start': 0, 'end': -1, 'text': 'recognized'},
    {'start': 6, 'end': 4, 'text': 'recognized'},
    {'start': 0, 'end': 50, 'text': 'recognized'},
    {'start': 0, 'end': 4, 'text': '  '},
])
def test_invalid_timestamp_or_empty_text_is_not_synthetic_success(row):
    result = speech()
    result['segments'] = [row]
    with pytest.raises(ValueError):
        api.validate_speech(result)


def write(folder, name, value):
    (folder / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def test_saved_translation_requires_all_ids_and_no_errors(tmp_path):
    write(tmp_path, 'transcript.json', [{'id': 's1'}, {'id': 's2'}])
    write(tmp_path, 'translations.json', {'s1': 'Поезд прибудет в девять.'})
    with pytest.raises(ValueError, match='every transcript'):
        api.validate_saved(tmp_path)
    write(tmp_path, 'translations.json', {'s1': 'Поезд прибудет в девять.', 's2': 'Сохраните субтитры.'})
    assert api.validate_saved(tmp_path)['translated_segments'] == 2
    write(tmp_path, 'translation-errors.json', ['Model returned invalid output'])
    with pytest.raises(ValueError, match='has errors'):
        api.validate_saved(tmp_path)


def test_notes_requires_persisted_notes_chapters_and_report(tmp_path):
    write(tmp_path, 'transcript.json', [{'id': 's1'}])
    write(tmp_path, 'translations.json', {'s1': 'Проверочная запись.'})
    write(tmp_path, 'notes.json', {'notes': [{'title': 'Тест'}]})
    write(tmp_path, 'chapters.json', [])
    with pytest.raises(ValueError, match='missing'):
        api.validate_saved(tmp_path, notes=True)
    write(tmp_path, 'chapters.json', [{'title': 'Глава'}])
    (tmp_path / 'report.html').write_text('<html>Тест</html>', encoding='utf-8')
    assert api.validate_saved(tmp_path, notes=True)['notes'] == 1


def test_acceptance_refuses_nonlocal_services_before_transmitting():
    client = api.InstalledAPI.__new__(api.InstalledAPI)
    client.origin = 'http://127.0.0.1:8000'
    with pytest.raises(ValueError, match='loopback'):
        client.request('/api/generate', base='https://example.com')


def test_failed_generation_preserves_answer_in_test_artifacts_and_remains_failed(tmp_path):
    client = api.InstalledAPI.__new__(api.InstalledAPI)
    client.root = tmp_path
    client.reports = tmp_path / 'reports'
    client.reports.mkdir()
    folder = tmp_path / 'windows-app/runtime/workspace/output/processed-test'
    folder.mkdir(parents=True)
    (folder / 'construction-result.md').write_text('Malformed model answer', encoding='utf-8')
    (folder / 'request-journal.json').write_text('must not be copied', encoding='utf-8')
    job = {'id': 'a' * 32, 'folder': folder.name, 'stage': 'notes', 'status': 'error',
           'error': 'Invalid headings', 'task': 'notes'}
    client.request = lambda _: {'job': job}
    with pytest.raises(RuntimeError, match='failed at notes: Invalid headings'):
        client.job_done(job)
    evidence = client.reports / ('failed-job-' + job['id'])
    assert (evidence / 'construction-result.md').read_text(encoding='utf-8') == 'Malformed model answer'
    assert not (evidence / 'request-journal.json').exists()
    assert json.loads((evidence / 'job.json').read_text(encoding='utf-8'))['status'] == 'error'


def test_workspace_wait_follows_new_create_job_and_propagates_failure(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location('workspace_acceptance', ROOT / 'windows-app/verify_workspace_ui.py')
    workspace = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(workspace)

    class Browser:
        def evaluate(self, expression):
            assert '#status' not in expression
            return 'new-job' if 'location.pathname' in expression else True

    expected = {'job': {'id': 'new-job', 'status': 'done'}}
    seen = []

    def completed(self, job, **kwargs):
        seen.append(job)
        return expected

    monkeypatch.setattr(workspace.InstalledAPI, 'job_done', completed)
    assert workspace.wait_workspace_job(Browser(), 'http://127.0.0.1:1234', tmp_path,
                                        tmp_path, previous='old-job') == expected
    assert seen == [{'id': 'new-job'}]

    def failed(self, job, **kwargs):
        raise RuntimeError('Real job failed')

    monkeypatch.setattr(workspace.InstalledAPI, 'job_done', failed)
    with pytest.raises(RuntimeError, match='Real job failed'):
        workspace.wait_workspace_job(Browser(), 'http://127.0.0.1:1234', tmp_path, tmp_path)


def test_timeout_keeps_last_state_and_only_disposable_worker_diagnostics(tmp_path, monkeypatch):
    client = api.InstalledAPI.__new__(api.InstalledAPI)
    client.root = tmp_path
    client.reports = tmp_path / 'reports'
    client.reports.mkdir()
    job = {'id': 'a' * 32, 'status': 'queued', 'folder': None, 'engine': 'whisper-local'}
    client.request = lambda _: {'job': job, 'result': None}
    worker = tmp_path / 'windows-app/runtime/workspace/output/jobs/worker.log'
    worker.parent.mkdir(parents=True)
    worker.write_text('Synthetic worker exception', encoding='utf-8')

    def deadline(read, *args, **kwargs):
        read()
        assert kwargs['timeout'] == 240
        raise TimeoutError('deadline')

    monkeypatch.setattr(api, 'wait_for', deadline)
    with pytest.raises(TimeoutError, match='status=queued'):
        client.job_done(job, timeout=240)
    evidence = client.reports / ('timeout-job-' + job['id'])
    assert json.loads((evidence / 'state.json').read_text(encoding='utf-8'))['status'] == 'queued'
    assert not (evidence / 'worker.log').exists()
    (tmp_path / '.acceptance-installation.json').write_text('{}')
    with pytest.raises(TimeoutError, match='240s'):
        client.job_done(job, timeout=240)
    assert (evidence / 'worker.log').read_text(encoding='utf-8') == 'Synthetic worker exception'


@pytest.mark.parametrize('stage', ['translation', 'notes'])
def test_postprocessing_acceptance_uses_shared_default_model(tmp_path, monkeypatch, stage):
    client = api.InstalledAPI.__new__(api.InstalledAPI)
    client.root, client.reports, client.ollama_model = tmp_path, tmp_path, 'selected:exact'
    client.connect = dict
    write(tmp_path, 'workflow-state.json', {'source_job': 'source'})
    source = {'job': {'folder': 'original'}}
    result = {'job': {'id': 'new', 'folder': 'processed'}}
    calls = []

    def request(path, *, body=None):
        calls.append((path, body))
        if path == '/api/speech?job=source':
            return source
        if path == '/api/native/postprocess':
            return result['job']
        if path.startswith('/api/subtitles?'):
            return b'00:00:00,000 --> 00:00:01,000'
        return {}

    client.request = request
    client.job_done = lambda job: result
    monkeypatch.setattr(api, 'validate_saved', lambda folder, **kwargs: {})
    folder = tmp_path / 'windows-app/runtime/workspace/output/processed'
    folder.mkdir(parents=True)
    (folder / 'report.html').write_text('Synthetic saved report', encoding='utf-8')
    assert client.run(stage)['status'] == 'PASS'
    assert ('/api/setup/ollama', {'model': 'selected:exact', 'task': 'translation'}) in calls
    assert ('/api/native/postprocess', {'folder': 'original',
            'task': 'notes' if stage == 'notes' else 'translate'}) in calls
