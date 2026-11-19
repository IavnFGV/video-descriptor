import json
from types import SimpleNamespace

import pytest

from video_descriptor import action_history, construction, gemini, gemini_run, jobs
from video_descriptor.editor import EditConflict
from video_descriptor.progress import ProgressLog


def reply(code, data=None):
    return SimpleNamespace(ok=code == 200, status_code=code, json=lambda: data,
                           text='Do not log test-api-key or an echoed prompt')


@pytest.mark.parametrize('codes', [(503, 200), (503, 503, 503)])
def test_construction_retries_only_generation_and_reports_attempts(tmp_path, monkeypatch, codes):
    events_file = tmp_path / 'events.jsonl'
    monkeypatch.setenv('VIDEO_DESCRIPTOR_EVENTS', str(events_file))
    folder = tmp_path / 'recording'
    folder.mkdir()
    speech = folder / 'speech.json'
    speech.write_text('saved transcript')
    log = ProgressLog(lambda _: None, 'recording', folder / 'requests')
    log.progress_file = folder / 'progress.json'
    log.update(stage='[4/5] Русский конспект')
    monkeypatch.setattr(construction, 'credentials', lambda _: {'api_key': 'test-api-key', 'gemini_consent': True})
    replies = iter(codes)
    calls, payloads, waits = [], [], []

    def request(method, url, **kwargs):
        calls.append(url.rsplit('/', 1)[-1])
        if method == 'GET':
            return reply(200, {'inputTokenLimit': 65536, 'outputTokenLimit': 4096})
        if url.endswith(':countTokens'):
            return reply(200, {'totalTokens': 1000})
        payloads.append(kwargs['json'])
        return reply(next(replies), {'candidates': [{'content': {'parts': [{'text': 'Completed notes'}]}}]})

    def wait(delay):
        progress = json.loads(log.progress_file.read_text(encoding='utf-8'))
        waits.append(delay)
        assert progress['requests'] == 1
        assert f'попытка {len(waits) + 1}/3 через {delay} сек' in progress['request_state']

    monkeypatch.setattr(gemini.requests, 'request', request)
    monkeypatch.setattr(gemini.time, 'sleep', wait)
    config = construction.validate({'provider': 'gemini', 'model': 'gemini-test'})
    if codes[-1] == 200:
        assert construction.generate(tmp_path, config, 'synthetic transcript', log) == 'Completed notes'
    else:
        with pytest.raises(gemini.GeminiServiceError, match='HTTP 503.*после 2 повторов'):
            construction.generate(tmp_path, config, 'synthetic transcript', log)

    assert calls == ['gemini-test', 'gemini-test:countTokens'] + ['gemini-test:generateContent'] * len(codes)
    assert payloads == [payloads[0]] * len(codes)
    assert waits == [20] * (len(codes) - 1)
    assert speech.read_text() == 'saved transcript'
    journal, = (folder / 'requests').iterdir()
    result = json.loads((journal / 'result.json').read_text(encoding='utf-8'))
    events_text = events_file.read_text(encoding='utf-8')
    assert all(text not in events_text for text in ('test-api-key', 'synthetic transcript', 'echoed prompt'))
    events = [event for line in events_text.splitlines() if (event := json.loads(line)).get('request_id') == journal.name]
    assert [event['action'] for event in events] == ['model_request_started'] + ['model_request_retry'] * len(waits) + ['model_request_finished']
    for attempt, event in enumerate(events[1:-1], start=2):
        assert event['code'] == 503 and event['attempt'] == attempt
        assert f'HTTP 503 · попытка {attempt}' in action_history.describe(event)
    assert result['status'] == events[-1]['status'] == ('complete' if codes[-1] == 200 else 'error')
    assert result.get('http_status') == events[-1].get('code') == (None if codes[-1] == 200 else 503)


@pytest.mark.parametrize(('method', 'endpoint', 'code'), [
    ('POST', ':generateContent', 429), ('POST', ':generateContent', 403),
    ('POST', ':generateContent', 500), ('POST', ':countTokens', 503), ('GET', '', 503),
])
def test_other_failures_do_not_retry(monkeypatch, method, endpoint, code):
    calls = []
    monkeypatch.setattr(gemini.requests, 'request', lambda *args, **kwargs: calls.append(args) or reply(code))
    monkeypatch.setattr(gemini.time, 'sleep', lambda _: pytest.fail('unexpected retry'))
    with pytest.raises(gemini.GeminiServiceError, match=f'HTTP {code}') as exc:
        gemini.call(method, gemini.BASE + '/models/gemini-test' + endpoint, 'test-api-key')
    assert exc.value.http_status == code and len(calls) == 1
    assert 'test-api-key' not in str(exc.value)


@pytest.fixture
def live_run(tmp_path):
    identifier = 'a' * 32
    folder, job_folder = tmp_path / 'output/notes', tmp_path / 'output/jobs' / identifier
    folder.mkdir(parents=True)
    job_folder.mkdir(parents=True)
    marker = {'id': identifier, 'started': 123.0}
    jobs.write_json(job_folder / 'job.json', {**marker, 'folder': folder.name, 'status': 'running',
                                               'construction': {'provider': 'gemini'}})
    log = ProgressLog(lambda _: None, folder.name, folder / 'requests')
    log.progress_file = folder / 'progress.json'
    log.gemini_run = (job_folder, marker['started'])
    log.update(gemini_run=marker)
    log('ready')
    return folder, job_folder, marker, log


def test_live_controls_are_scoped_to_the_current_run(tmp_path, live_run):
    folder, job_folder, marker, _ = live_run
    values = {**marker, 'folder': folder.name, 'repeat': True, 'model': 'gemini-next'}
    with pytest.raises(ValueError):
        gemini_run.save(tmp_path, {**values, 'model': 'gemini-foo/bar'})
    assert gemini_run.save(tmp_path, values) == {**marker, 'repeat': True, 'model': 'gemini-next'}
    assert gemini_run.controls(job_folder, 124.0) == {'model': '', 'repeat': False}
    (job_folder / 'stop-request.json').touch()
    with pytest.raises(EditConflict):
        gemini_run.save(tmp_path, values)


@pytest.mark.parametrize('ending', ['success', 'disable', 'stop', 'quota', 'does-not-fit'])
def test_live_retry_and_model_selection(tmp_path, live_run, monkeypatch, ending):
    folder, job_folder, marker, log = live_run
    values = {**marker, 'folder': folder.name, 'repeat': True, 'model': ''}
    gemini_run.save(tmp_path, values)
    monkeypatch.setattr(construction, 'credentials', lambda _: {'api_key': 'test-key', 'gemini_consent': True})
    checks, sent = [], []
    clock = [100.0]
    monkeypatch.setattr(construction.time, 'monotonic', lambda: clock[0])

    def request(method, url, **kwargs):
        model = url.rsplit('/', 1)[-1].split(':')[0]
        if method == 'GET':
            return reply(200, {'inputTokenLimit': 65536,
                               'outputTokenLimit': 1 if ending == 'does-not-fit' and model == 'gemini-next' else 4096,
                               'supportedGenerationMethods': ['generateContent']})
        if url.endswith(':countTokens'):
            checks.append(model)
            return reply(200, {'totalTokens': 1000})
        progress = json.loads(log.progress_file.read_text(encoding='utf-8'))
        assert not progress.get('gemini_retry_wait')
        sent.append(model)
        if ending == 'quota':
            return reply(429)
        if len(sent) <= 3:
            return reply(503)
        return reply(200, {'candidates': [{'content': {'parts': [{'text': 'Done'}]}}]})

    def wait(seconds):
        progress = json.loads(log.progress_file.read_text(encoding='utf-8'))
        countdown = progress['gemini_retry_wait']
        assert countdown['seconds'] == 20
        assert countdown['until'] - progress['updated'] == pytest.approx(20, abs=.5)
        assert seconds == 1
        clock[0] += seconds
        if len(sent) != 3 or clock[0] != 141:
            return
        if ending == 'stop':
            (job_folder / 'stop-request.json').touch()
        else:
            gemini_run.save(tmp_path, {**values, 'model': 'gemini-next', 'repeat': ending != 'disable'})

    monkeypatch.setattr(gemini.requests, 'request', request)
    monkeypatch.setattr(construction.time, 'sleep', wait)
    config = construction.validate({'provider': 'gemini', 'model': 'gemini-first'})
    if ending == 'success':
        assert construction.generate(tmp_path, config, 'Transcript', log) == 'Done'
        assert construction.generate(tmp_path, config, 'Next block', log) == 'Done'
        assert sent == ['gemini-first'] * 3 + ['gemini-next'] * 2
        assert checks == ['gemini-first', 'gemini-next', 'gemini-next']
        assert len(list((folder / 'requests').iterdir())) == 3
    else:
        expected = {'disable': 'HTTP 503', 'stop': 'остановлено', 'quota': 'HTTP 429', 'does-not-fit': 'лимит ответа'}
        with pytest.raises((ValueError, RuntimeError, gemini.GeminiServiceError), match=expected[ending]):
            construction.generate(tmp_path, config, 'Transcript', log)
        assert sent == ['gemini-first'] * (1 if ending == 'quota' else 3)
    assert config['model'] == 'gemini-first'
    assert not json.loads(log.progress_file.read_text(encoding='utf-8')).get('gemini_retry_wait')
