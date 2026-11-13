"""Deterministic inference routing and immutable queue configuration; no real models."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

import pytest

from video_descriptor import (
    construction,
    jobs,
    llm_provider,
    notes,
    postprocess,
    translate,
    translation_settings,
)
from video_descriptor.progress import ProgressLog


@pytest.fixture
def servers():
    instances = []

    def start():
        state = {'models': ['chosen'], 'requests': [], 'answer': '[[s0001]]\nПеревод', 'status': 200, 'on_request': None, 'invalid': False}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, value, code=200):
                body = json.dumps(value).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == '/api/tags':
                    return self.reply({'models': [{'name': name} for name in state['models']]})
                if self.path == '/v1/models':
                    return self.reply({'data': [{'id': name} for name in state['models']]})
                self.reply({}, 404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path == '/api/show':
                    return self.reply({'model_info': {'test.context_length': 32768}, 'capabilities': ['completion']})
                state['requests'].append((self.path, body))
                if state['on_request']:
                    state['on_request']()
                if state['status'] != 200:
                    return self.reply({'error': 'private-secret transcript-content'}, state['status'])
                if state['invalid']:
                    return self.reply({'error': 'private-secret transcript-content'})
                if self.path == '/api/chat':
                    return self.reply({'message': {'content': state['answer']}, 'done': True})
                if self.path == '/v1/chat/completions':
                    return self.reply({'choices': [{'message': {'content': state['answer']}, 'finish_reason': 'stop'}]})
                self.reply({}, 404)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        thread.start()
        instances.append((server, thread))
        return f'http://127.0.0.1:{server.server_port}', state

    yield start
    for server, thread in instances:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def recording(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('VIDEO_DESCRIPTOR_EVENTS', str(tmp_path / 'events.jsonl'))
    folder = tmp_path / 'output/source'
    folder.mkdir(parents=True)
    rows = [{'id': 's1', 'start': 0, 'end': 10, 'text': 'First source', 'speaker': 'unknown'},
            {'id': 's2', 'start': 1000, 'end': 1010, 'text': 'Second source', 'speaker': 'unknown'}]
    jobs.write_json(folder / 'manifest.json', {'video': str(tmp_path / 'video.mp4')})
    jobs.write_json(folder / 'speech.json', {'status': 'done', 'segments': rows, 'translations': {}})
    jobs.write_json(folder / 'transcript.json', rows)
    monkeypatch.setattr(translate, 'refresh_reports', lambda *args: None)
    monkeypatch.setattr(construction, 'render', lambda *args, **kwargs: None)
    # Tokenizer metadata is orthogonal to transport routing, and must remain offline.
    class Counter:
        mode = 'byte-bound'

        def __call__(self, text):
            return len(text.encode())
    monkeypatch.setattr(translate, 'load_counter', lambda *args: Counter())
    monkeypatch.setattr(construction, 'load_counter', lambda *args: Counter())
    return tmp_path, folder


def configure(root, provider, endpoint, model='chosen'):
    translation_settings.save(root, {'provider': provider, 'ollama_model': model,
                                     'lmstudio_model': model, 'lmstudio_url': endpoint + '/v1'})
    jobs.write_json(root / '.devcontainer/ollama-connection.json', {'url': endpoint})


@pytest.mark.parametrize('provider', ['ollama', 'lmstudio'])
def test_translation_keeps_route_and_model_between_batches(recording, servers, monkeypatch, provider):
    root, folder = recording
    endpoint, state = servers()
    other, redirected = servers()
    configure(root, provider, endpoint)
    state['on_request'] = lambda: configure(root, 'lmstudio' if provider == 'ollama' else 'ollama', other, 'different')
    monkeypatch.setattr(sys, 'argv', ['translate', str(folder)])
    assert translate.main() == 0
    assert len(state['requests']) == 2
    assert redirected['requests'] == []
    for path, body in state['requests']:
        assert path == ('/api/chat' if provider == 'ollama' else '/v1/chat/completions')
        assert body['model'] == 'chosen'
        assert body['messages'][0]['content'] == translate.PROMPT
        assert (body['options']['num_predict'] if provider == 'ollama' else body['max_tokens']) == 4096
    saved = jobs.read_json(folder / 'llm-settings.json')
    assert saved['provider'] == provider and saved['model'] == 'chosen'
    assert saved['endpoint'] == endpoint + ('/v1' if provider == 'lmstudio' else '')
    assert jobs.read_json(folder / 'translations.json') == {'s1': 'Перевод', 's2': 'Перевод'}


@pytest.mark.parametrize('provider', ['ollama', 'lmstudio'])
@pytest.mark.parametrize('kind', ['notes', 'article'])
def test_notes_and_article_jobs_use_pinned_endpoint_and_parameters(recording, servers, monkeypatch, provider, kind):
    root, source = recording
    endpoint, state = servers()
    other, redirected = servers()
    configure(root, provider, endpoint)
    config = {'result_kind': kind, 'strategy': 'whole', 'auto_context': False,
              'context_tokens': 32768, 'output_tokens': 1024,
              'prompt': 'EXACT NOTES PROMPT', 'article_prompt': 'EXACT ARTICLE PROMPT'}
    job = construction.enqueue_notes(root, source.name, config)
    assert job['construction']['provider'] == provider
    assert job['construction']['model'] == 'chosen'
    assert job['llm']['parameters']['output_tokens'] == 1024
    configure(root, 'lmstudio' if provider == 'ollama' else 'ollama', other, 'different')
    for key, value in llm_provider.environment(job['llm']).items():
        if key.startswith('VIDEO_DESCRIPTOR_') and key in {'VIDEO_DESCRIPTOR_LLM_SNAPSHOT', 'VIDEO_DESCRIPTOR_JOB_OLLAMA_URL', 'VIDEO_DESCRIPTOR_JOB_LMSTUDIO_URL'}:
            monkeypatch.setenv(key, value)
    state['answer'] = ('Generated article' if kind == 'article' else
                       '## Оглавление\n### [00:00:00] Topic\n\n## Конспект\n### [00:00:00] Topic\nSummary.')
    result = root / 'output' / job['folder']
    construction.run(root, result, job['construction'])
    assert redirected['requests'] == [] and len(state['requests']) == 1
    _, payload = state['requests'][0]
    assert payload['model'] == 'chosen'
    assert payload['messages'][0]['content'] == ('EXACT ARTICLE PROMPT' if kind == 'article' else 'EXACT NOTES PROMPT')
    assert (payload['options']['num_predict'] if provider == 'ollama' else payload['max_tokens']) == 1024
    assert (result / ('article.md' if kind == 'article' else 'notes.md')).exists()
    # The real queue worker forwards precisely the same secret-free snapshot on resume.
    calls = []
    monkeypatch.setattr(jobs, 'run_process', lambda *args, **kwargs: calls.append(kwargs) or Mock(returncode=0))
    jobs.run_job(root, jobs.jobs_dir(root) / job['id'], job)
    assert job['status'] == 'done'
    assert json.loads(calls[0]['env']['VIDEO_DESCRIPTOR_LLM_SNAPSHOT']) == job['llm']


@pytest.mark.parametrize('provider', ['ollama', 'lmstudio'])
@pytest.mark.parametrize('failure', ['missing', 'http', 'invalid'])
def test_provider_errors_do_not_fallback_or_expose_server_body(recording, servers, monkeypatch, caplog, provider, failure):
    root, folder = recording
    endpoint, state = servers()
    configure(root, provider, endpoint)
    if failure == 'missing':
        state['models'] = []
    elif failure == 'http':
        state['status'] = 401
    else:
        state['invalid'] = True
    monkeypatch.setattr(sys, 'argv', ['translate', str(folder)])
    assert translate.main() == 1
    assert len(state['requests']) == (0 if failure == 'missing' else 2)
    assert 'private-secret' not in caplog.text
    assert 'transcript-content' not in caplog.text
    assert 'private-secret' not in (root / 'events.jsonl').read_text(encoding='utf-8')
    assert all(body['model'] == 'chosen' for _, body in state['requests'])


@pytest.mark.parametrize('task', ['summarize', 'filter', 'quiz_explanation', 'route_vision'])
@pytest.mark.parametrize('provider', ['ollama', 'lmstudio'])
def test_legacy_llm_operations_dispatch_to_selected_adapter(recording, servers, provider, task):
    root, _ = recording
    endpoint, state = servers()
    configure(root, provider, endpoint)
    state['answer'] = '{"value":"generated"}'
    log = ProgressLog(lambda _: None, 'legacy', root / 'requests')
    log.llm_settings = llm_provider.runtime(llm_provider.snapshot(root), translation_settings.load(root))
    schema = {'type': 'object', 'properties': {'value': {'type': 'string'}}}
    answer = notes.chat_json('EXACT PROMPT', {'source': 'material'}, schema, 'chosen', endpoint, log, task=task)
    assert json.loads(answer) == {'value': 'generated'}
    assert state['requests'][0][1]['model'] == 'chosen'
    assert state['requests'][0][1]['messages'][0]['content'] == 'EXACT PROMPT'
    if provider == 'lmstudio':
        assert state['requests'][0][1]['response_format']['json_schema']['schema'] == schema


def test_queue_snapshots_are_additive_secret_free_and_not_re_resolved(recording, servers):
    root, _ = recording
    endpoint, _ = servers()
    configure(root, 'lmstudio', endpoint)
    translation_settings.save(root, {'lmstudio_api_key': 'private-secret'})
    job = {'thinking': True}
    jobs.capture_llm(root, job)
    before = json.loads(json.dumps(job))
    configure(root, 'ollama', endpoint, 'other')
    jobs.capture_llm(root, job)
    assert job == before
    assert 'private-secret' not in json.dumps(job)
    value = llm_provider.snapshot(root, parameters={'api_key': 'private-secret', 'prompt': 'private-secret', 'output_tokens': 1234})
    assert value['parameters'] == {'output_tokens': 1234}
    assert 'private-secret' not in llm_provider.environment(value)['VIDEO_DESCRIPTOR_LLM_SNAPSHOT']


def test_postprocess_snapshots_translation_and_construction_separately(recording, servers):
    root, _ = recording
    endpoint, _ = servers()
    configure(root, 'lmstudio', endpoint)
    job = postprocess.enqueue(root, 'source', 'notes', 'chosen', endpoint + '/v1',
                              construction={'provider': 'lmstudio', 'model': 'chosen', 'output_tokens': 1024},
                              translation_provider='lmstudio')
    assert job['llm']['parameters']['output_tokens'] == 1024
    assert job['translation_llm']['parameters']['output_tokens'] == 4096
    assert job['llm']['endpoint'] == job['translation_llm']['endpoint'] == endpoint + '/v1'


@pytest.mark.parametrize('provider', ['ollama', 'lmstudio'])
def test_queued_translation_worker_does_not_read_new_global_route(recording, servers, monkeypatch, provider):
    root, _ = recording
    endpoint, state = servers()
    other, redirected = servers()
    configure(root, provider, endpoint)
    job = postprocess.enqueue(root, 'source', 'translate', 'chosen', endpoint + ('/v1' if provider == 'lmstudio' else ''),
                              translation_provider=provider)
    configure(root, 'lmstudio' if provider == 'ollama' else 'ollama', other, 'different')

    def run_process(folder, command, **kwargs):
        assert command[3] == 'video_descriptor.translate'
        with monkeypatch.context() as child:
            child.setattr(sys, 'argv', [command[3], *command[4:]])
            child.setenv('VIDEO_DESCRIPTOR_LLM_SNAPSHOT', kwargs['env']['VIDEO_DESCRIPTOR_LLM_SNAPSHOT'])
            return Mock(returncode=translate.main())

    monkeypatch.setattr(postprocess, 'run_process', run_process)
    postprocess.run(root, jobs.jobs_dir(root) / job['id'], job, None)
    assert job['stage'] == 'done'
    assert len(state['requests']) == 2 and redirected['requests'] == []
    assert all(body['model'] == 'chosen' for _, body in state['requests'])


def test_unified_preferences_supply_construction_defaults_without_losing_prompts(recording, servers):
    root, _ = recording
    endpoint, _ = servers()
    configure(root, 'lmstudio', endpoint)
    construction.save_settings(root, {'provider': 'ollama', 'model': 'old-model', 'prompt': 'CUSTOM PROMPT'})
    settings = construction.load_settings(root)
    assert settings['provider'] == 'lmstudio' and settings['model'] == 'chosen'
    assert settings['prompt'] == 'CUSTOM PROMPT'
    explicit = construction.configured(root, {'provider': 'ollama', 'model': 'explicit'})
    assert explicit['provider'] == 'ollama' and explicit['model'] == 'explicit'


def test_missing_selection_is_an_error_instead_of_a_default_model(recording, monkeypatch):
    root, folder = recording
    translation_settings.save(root, {'provider': 'ollama', 'ollama_model': ''})
    monkeypatch.setenv('OLLAMA_MODEL', 'must-not-be-selected')
    monkeypatch.setattr(sys, 'argv', ['translate', str(folder)])
    assert translate.main() == 1
    with pytest.raises(ValueError, match='название модели'):
        construction.configured(root, {})


def test_credentials_for_a_changed_endpoint_are_never_attached_to_a_pinned_job(recording, servers, monkeypatch):
    root, _ = recording
    first, _ = servers()
    second, _ = servers()
    configure(root, 'lmstudio', first)
    value = llm_provider.snapshot(root)
    configure(root, 'lmstudio', second)
    translation_settings.save(root, {'lmstudio_api_key': 'private-secret'})
    monkeypatch.setenv('VIDEO_DESCRIPTOR_JOB_LMSTUDIO_URL', value['endpoint'])
    monkeypatch.setenv('VIDEO_DESCRIPTOR_LLM_SNAPSHOT', json.dumps(value))
    with pytest.raises(ValueError, match='адрес задания') as error:
        llm_provider.runtime(value, translation_settings.load(root))
    assert 'private-secret' not in str(error.value)


def test_existing_gemini_transport_preserves_shared_task_schema_and_parameters(recording, monkeypatch):
    from video_descriptor import gemini
    root, _ = recording
    captured = []
    monkeypatch.setattr(gemini, 'call', lambda *args, **kwargs: captured.append(kwargs['json']) or {
        'candidates': [{'content': {'parts': [{'text': '{"keep":[]}'}]}, 'finishReason': 'STOP'}]})
    value = llm_provider.snapshot(root, settings={'provider': 'gemini', 'model': 'gemini-test'})
    settings = llm_provider.runtime(value, {'api_key': 'private-secret'})
    schema = {'type': 'object', 'properties': {'keep': {'type': 'array', 'items': {'type': 'integer'}}}}
    assert llm_provider.generate(settings, 'EXACT FILTER PROMPT', 'material', output_tokens=1234,
                                 task='filter', schema=schema, images=['base64-image']) == '{"keep":[]}'
    payload = captured[0]
    assert payload['systemInstruction']['parts'][0]['text'] == 'EXACT FILTER PROMPT'
    assert payload['generationConfig']['maxOutputTokens'] == 1234
    assert payload['generationConfig']['responseJsonSchema'] == schema
    assert payload['contents'][0]['parts'][1]['inlineData']['data'] == 'base64-image'
    assert 'private-secret' not in json.dumps(payload)


def test_legacy_explicit_ollama_environment_remains_supported(recording, servers, monkeypatch):
    _, folder = recording
    endpoint, state = servers()
    monkeypatch.setenv('OLLAMA_MODEL', 'chosen')
    monkeypatch.setenv('OLLAMA_BASE_URL', endpoint)
    monkeypatch.setattr(sys, 'argv', ['translate', str(folder)])
    assert translate.main() == 0
    assert len(state['requests']) == 2
    assert all(body['model'] == 'chosen' for _, body in state['requests'])
