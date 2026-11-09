import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from video_descriptor import construction, lmstudio, translation_settings
from video_descriptor.progress import ProgressLog


@pytest.fixture
def server():
    state = {'finish': 'stop', 'status': 200, 'calls': [], 'answer': 'Ответ'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.reply({'models': [{'type': 'llm', 'key': 'local/model',
                                   'loaded_instances': [{'id': 'local/model', 'config': {'context_length': 8192}}]}]}
                       if self.path == '/api/v1/models' else {'data': [{'id': 'local/model'}]})

        def do_POST(self):
            state['calls'].append((self.path, self.headers.get('Authorization'),
                                   json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            self.reply({'choices': [{'message': {'content': state['answer']}, 'finish_reason': state['finish']}],
                        'usage': {'prompt_tokens': 10, 'completion_tokens': 2}})

        def reply(self, value):
            self.send_response(state['status'])
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as http:
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            yield {'lmstudio_url': f'http://127.0.0.1:{http.server_port}/v1', 'lmstudio_api_key': 'private-test-token'}, state
        finally:
            http.shutdown()
            thread.join()


def test_inventory_loaded_context_generation_and_audit(server, tmp_path, monkeypatch):
    settings, state = server
    events = tmp_path / 'events.jsonl'
    monkeypatch.setenv('VIDEO_DESCRIPTOR_EVENTS', str(events))
    assert lmstudio.models(settings) == [{'id': 'local/model', 'title': 'local/model'}]
    assert lmstudio.context_limit(settings, 'local/model') == 8192
    log = ProgressLog(lambda _: None, 'test', tmp_path / 'recording/requests')
    assert lmstudio.generate(settings, 'local/model', 'private-prompt', 'private-transcript', log) == 'Ответ'
    path, token, payload = state['calls'][0]
    assert path == '/v1/chat/completions' and token == 'Bearer private-test-token'
    assert payload['stream'] is False and payload['model'] == 'local/model'
    audit = events.read_text(encoding='utf-8')
    assert 'model_request_started' in audit and 'model_request_finished' in audit
    assert all(secret not in audit for secret in ('private-test-token', 'private-prompt', 'private-transcript'))
    assert 'private-test-token' not in ''.join(p.read_text(encoding='utf-8') for p in tmp_path.rglob('*.json'))


@pytest.mark.parametrize('finish', ['length', 'tool_calls', None])
def test_incomplete_answers_are_rejected_and_recorded(server, tmp_path, finish):
    settings, state = server
    state['finish'] = finish
    log = ProgressLog(lambda _: None, 'test', tmp_path / 'requests')
    with pytest.raises(ValueError, match='не завершён'):
        lmstudio.generate(settings, 'local/model', 'prompt', 'text', log)
    result = json.loads(next((tmp_path / 'requests').glob('*/result.json')).read_text())
    assert result['status'] == 'error'


def test_auth_error_does_not_expose_response_or_token(server):
    settings, state = server
    state['status'] = 401
    with pytest.raises(ValueError, match='API-токен') as error:
        lmstudio.models(settings)
    assert 'private-test-token' not in str(error.value)


@pytest.mark.parametrize('url', ['https://example.com/v1', 'http://user:secret@localhost:1234/v1',
                                 'http://localhost:1234/v1?token=secret', 'http://localhost:1234/other',
                                 'http://localhost:bad/v1'])
def test_only_local_connection_urls(url):
    with pytest.raises(ValueError):
        lmstudio.base_url(url)


def test_preferences_keep_providers_independent_and_hide_token(tmp_path):
    saved = translation_settings.save(tmp_path, {'provider': 'lmstudio', 'lmstudio_model': 'local/model',
                                                'lmstudio_api_key': 'private-token'})
    assert saved['lmstudio_has_key'] and saved['lmstudio_model'] == 'local/model'
    assert 'private-token' not in json.dumps(saved)
    assert translation_settings.load(tmp_path)['lmstudio_api_key'] == 'private-token'
    translation_settings.save(tmp_path, {'lmstudio_api_key': '', 'ollama_model': 'existing:9b'})
    assert translation_settings.load(tmp_path)['lmstudio_api_key'] == 'private-token'


def test_construction_uses_lmstudio_and_loaded_limits(server, monkeypatch, tmp_path):
    settings, _ = server
    monkeypatch.setattr(construction, 'credentials', lambda _: settings)
    config = construction.validate({'provider': 'lmstudio', 'model': 'local/model', 'output_tokens': 1024})
    assert construction.available_models(None, 'lmstudio')[0]['id'] == 'local/model'
    assert construction.actual_limits(None, config)['context_tokens'] == 8192
    log = ProgressLog(lambda _: None, 'test', tmp_path / 'requests')
    assert construction.generate(None, config, 'Transcript', log) == 'Ответ'
    with pytest.raises(ValueError, match='недоступна'):
        construction.actual_limits(None, {**config, 'model': 'missing'})


def test_translation_cli_pins_lmstudio_despite_current_ollama_preference(server, tmp_path, monkeypatch):
    from video_descriptor import translate
    settings, state = server
    state['answer'] = '[[s0001]]\nПривет'
    (tmp_path / 'transcript.json').write_text(json.dumps([
        {'id': 's1', 'start': 0, 'end': 1, 'text': 'Hello'}]), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['translate', str(tmp_path), '--model', 'local/model',
                                     '--lmstudio-model', 'local/model', '--lmstudio-url', settings['lmstudio_url']])
    monkeypatch.setattr(translate, 'translation_settings', lambda: {**settings, 'provider': 'ollama', 'ollama_model': 'other'})
    monkeypatch.setattr(translate, 'refresh_reports', lambda *a: None)
    assert translate.main() == 0
    assert json.loads((tmp_path / 'translations.json').read_text(encoding='utf-8')) == {'s1': 'Привет'}
    plan = json.loads((tmp_path / 'translation-plan.json').read_text(encoding='utf-8'))
    assert plan['provider'] == 'lmstudio' and plan['model'] == 'local/model'
    assert state['calls'][0][2]['model'] == 'local/model'


def test_translation_preserves_markers(monkeypatch):
    from video_descriptor import translate
    from video_descriptor.models import Source
    log = ProgressLog(lambda _: None, 'test')
    log.translation_settings = {'provider': 'lmstudio'}
    monkeypatch.setattr(lmstudio, 'generate', lambda *a, **kw: '[[s0001]]\nПривет')
    rows = [Source(id='s1', start=0, end=1, text='Hello')]
    assert translate.translate_batch(rows, 'local/model', '', log) == {'s1': 'Привет'}
    monkeypatch.setattr(lmstudio, 'generate', lambda *a, **kw: 'Без меток')
    with pytest.raises(ValueError, match='метк'):
        translate.translate_batch(rows, 'local/model', '', log)
