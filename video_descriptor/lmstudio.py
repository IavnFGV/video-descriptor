"""Local LM Studio adapter; never manages the user's server or downloads models."""
import json
import os
import uuid
from urllib.parse import urlsplit

import requests

from .action_history import record
from .progress import update_status
from .request_log import RequestJournal

DEFAULT_URL = 'http://127.0.0.1:1234/v1'


def base_url(value):
    if not isinstance(value, str):
        raise TypeError('Укажите локальный адрес LM Studio')
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path.rstrip('/') not in {'', '/v1'}):
        raise ValueError('LM Studio: разрешён локальный HTTP-адрес без credentials, например ' + DEFAULT_URL)
    try:
        _ = parsed.port
    except ValueError:
        raise ValueError('LM Studio: некорректный порт') from None
    return value.rstrip('/').removesuffix('/v1') + '/v1'


def call(settings, method, endpoint, **kwargs):
    url = base_url(settings.get('lmstudio_url', DEFAULT_URL))
    token = settings.get('lmstudio_api_key') or os.getenv('LM_STUDIO_API_TOKEN', '')
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    operation = uuid.uuid4().hex
    stage = 'inference' if method == 'POST' else 'inventory'
    record('operation_started', operation_id=operation, component='lmstudio', stage=stage, status='running')
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.request(method, (url.removesuffix('/v1') if endpoint.startswith('/api/') else url) + endpoint, headers=headers,
                                       timeout=(5, 600) if method == 'POST' else (5, 15),
                                       allow_redirects=False, **kwargs)
            if response.status_code in {401, 403}:
                raise ValueError('LM Studio: проверьте API-токен в настройках подключения')
            if not 200 <= response.status_code < 300:
                raise ValueError(f'LM Studio: HTTP {response.status_code}. Проверьте сервер, модель и контекст')
            result = response.json()
            record('operation_finished', operation_id=operation, component='lmstudio', stage=stage, status='done')
            return result
    except (requests.RequestException, json.JSONDecodeError):
        record('operation_failed', operation_id=operation, component='lmstudio', stage=stage, status='error', reason='connection_or_response')
        raise ValueError('LM Studio недоступен или вернул неверный ответ. Включите Local Server и проверьте адрес') from None
    except BaseException as exc:
        record('operation_failed', operation_id=operation, component='lmstudio', stage=stage, status='error', reason=type(exc).__name__)
        raise


def models(settings):
    result = call(settings, 'GET', '/models')
    rows = result.get('data') if isinstance(result, dict) else None
    if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not isinstance(row.get('id'), str)
            or not row['id'].strip() for row in rows):
        raise ValueError('LM Studio: некорректный список моделей')
    return [{'id': row['id'], 'title': row['id']} for row in rows]


def context_limit(settings, model):
    # Native metadata reports the loaded context, not merely the model's theoretical maximum.
    try:
        url = base_url(settings.get('lmstudio_url', DEFAULT_URL))
        metadata = call({**settings, 'lmstudio_url': url}, 'GET', '/api/v1/models')
        for row in metadata['models']:
            if row.get('type') != 'llm':
                continue
            for instance in row.get('loaded_instances', []):
                if model in {row.get('key'), instance.get('id')}:
                    limit = instance['config']['context_length']
                    if type(limit) is int and limit > 0:
                        return limit
    except (ValueError, KeyError, TypeError):
        pass
    raise ValueError('LM Studio: не удалось определить загруженный контекст. Загрузите модель или задайте контекст вручную по настройкам LM Studio')


def generate(settings, model, prompt, text, log, *, output_tokens=4096, task='construction'):
    payload = {'model': model, 'messages': [{'role': 'system', 'content': prompt},
                                          {'role': 'user', 'content': text}],
               'temperature': 0, 'max_tokens': output_tokens, 'stream': False}
    journal = None
    if log:
        log.begin_request(task, model, len(prompt) + len(text), len(json.dumps(payload).encode()), 0, output_tokens)
        log.update(provider='lmstudio')
        if log.journal_dir:
            journal = RequestJournal(log.journal_dir, base_url(settings.get('lmstudio_url', DEFAULT_URL)) + '/chat/completions',
                                     payload, log.snapshot(), task)
            update_status(log, request_log=str(journal.folder))
        log('LM Studio: ожидаем ответ модели')
    try:
        data = call(settings, 'POST', '/chat/completions', json=payload)
        choice = data['choices'][0]
        answer = choice['message'].get('content')
        if journal:
            journal.write('lmstudio-response.json', data)
            journal.event({'message': {'content': answer if isinstance(answer, str) else ''}})
        if choice.get('finish_reason') != 'stop':
            raise ValueError('LM Studio: ответ не завершён; проверьте лимит ответа и модель')
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError('LM Studio: модель вернула пустой текст')
        if log:
            usage = data.get('usage', {})
            log.update(received=len(answer), input_tokens=usage.get('prompt_tokens'),
                       output_tokens=usage.get('completion_tokens'), request_state='ответ получен')
            log('LM Studio: ответ получен, проверяем результат')
        if journal:
            journal.finish('done')
        return answer
    except BaseException as exc:
        if journal:
            journal.finish('error', type(exc).__name__)
        if isinstance(exc, (KeyError, IndexError, TypeError)):
            raise ValueError('LM Studio: некорректный ответ модели') from None  # noqa: TRY004 — normalize malformed server responses.
        raise
