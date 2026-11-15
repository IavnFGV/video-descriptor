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


@pytest.mark.parametrize('with_ollama,translate_after', [(False, False), (True, False), (True, True)])
def test_installed_ui_workflow_uses_notes_tab_without_retired_translation(
        monkeypatch, tmp_path, with_ollama, translate_after):
    spec = importlib.util.spec_from_file_location('workspace_acceptance', ROOT / 'windows-app/verify_workspace_ui.py')
    workspace = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(workspace)
    actions, followed, verified = [], [], []

    class Process:
        def poll(self):
            return 0

    class Browser:
        sock = type('Socket', (), {'close': lambda self: None})()

        def evaluate(self, expression):
            if 'getClientRects' in expression:
                return 0  # Settings are already closed.
            if expression.endswith('.disabled') and not expression.startswith('!'):
                return False
            if 'getAttribute("aria-selected")' in expression:
                return actions[-1] == ('click', '#workspace-tab-' + ('notes' if with_ollama else 'transcript'))
            return True

        def click(self, selector):
            assert selector in {'#new-record-open', '#start', '#workspace-tab-notes',
                                '#workspace-tab-transcript', '#construction-run'}
            actions.append(('click', selector))

        def fill(self, selector, value):
            assert selector in {'#title', '#language', '#recording-notes',
                                '#construction-provider', '#construction-model'}
            actions.append(('fill', selector, value))

        def call(self, method, **kwargs):
            return {'root': {'nodeId': 1}, 'nodeId': 2}

        def screenshot(self, target):
            pass

    def completed(cdp, base, root, output, previous=None, **kwargs):
        followed.append(previous)
        return {'job': {'id': 'notes' if previous else 'speech', 'folder': 'result',
                        'status': 'done', 'translate_after': translate_after},
                'result': speech()}

    def ready(read, predicate=bool, **kwargs):
        value = read()
        assert predicate(value), 'Unexpected installed UI wait in simulated workflow'
        return value

    monkeypatch.setattr(workspace, 'wait_for', ready)
    monkeypatch.setattr(workspace.subprocess, 'Popen', lambda *args, **kwargs: Process())
    monkeypatch.setattr(workspace, 'read_http', lambda _: json.dumps([
        {'type': 'page', 'url': 'http://127.0.0.1:1234/', 'id': 'target',
         'webSocketDebuggerUrl': 'unused'}]).encode())
    monkeypatch.setattr(workspace, 'CDP', lambda _: Browser())
    monkeypatch.setattr(workspace, 'wait_workspace_job', completed)
    monkeypatch.setattr(workspace, 'run', lambda args, evidence: verified.append(args))
    output = tmp_path / 'reports'
    if with_ollama and translate_after:
        with pytest.raises(AssertionError):
            workspace.installed_workflow(tmp_path, 1234, output, with_ollama=True, ollama_model='selected:exact')
        assert not verified
        assert json.loads((output / 'workspace-ui.json').read_text())['status'] == 'FAIL'
        return
    result = workspace.installed_workflow(tmp_path, 1234, output, with_ollama=with_ollama,
                                          ollama_model='selected:exact')
    assert result['status'] == 'PASS'
    assert followed == ([None, 'speech'] if with_ollama else [None])
    assert len(verified) == 1 and verified[0].edit_reply
    if with_ollama:
        assert actions.index(('click', '#workspace-tab-notes')) < actions.index(('fill', '#recording-notes', '__new__'))
        assert ('fill', '#construction-model', 'selected:exact') in actions
        assert actions[-1] == ('click', '#construction-run')
        assert verified[0].notes_folder == 'result'
    else:
        assert verified[0].notes_folder is None


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
