import json
from types import SimpleNamespace

import pytest

from video_descriptor import action_history, construction, gemini
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
    monkeypatch.setattr(gemini.random, 'randint', lambda *_: 2)
    monkeypatch.setattr(gemini.time, 'sleep', wait)
    config = construction.validate({'provider': 'gemini', 'model': 'gemini-test'})
    if codes[-1] == 200:
        assert construction.generate(tmp_path, config, 'synthetic transcript', log) == 'Completed notes'
    else:
        with pytest.raises(gemini.GeminiServiceError, match='HTTP 503.*после 2 повторов'):
            construction.generate(tmp_path, config, 'synthetic transcript', log)

    assert calls == ['gemini-test', 'gemini-test:countTokens'] + ['gemini-test:generateContent'] * len(codes)
    assert payloads == [payloads[0]] * len(codes)
    assert waits == [17, 32][:len(codes) - 1]
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
