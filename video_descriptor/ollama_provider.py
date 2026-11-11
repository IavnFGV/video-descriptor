"""External Ollama HTTP adapter; no runtime or model lifecycle ownership."""
import uuid

import requests

from .action_history import record
from .llm_provider import require_model
from .ollama_connection import endpoint_url


class Ollama:
    def __init__(self, endpoint):
        self.endpoint = endpoint_url(endpoint)

    def request(self, path, body=None, timeout=5):
        operation = uuid.uuid4().hex
        stage = {'/api/version': 'connection', '/api/tags': 'discovery', '/api/show': 'metadata', '/api/generate': 'generation'}.get(path, 'connection')
        record('llm_request', stage=stage, status='started', operation_id=operation)
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = (session.get(self.endpoint + path, timeout=timeout) if body is None else
                            session.post(self.endpoint + path, json=body, timeout=(5, timeout)))
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or data.get('error'):
                    raise ValueError
                record('llm_request', stage=stage, status='done', operation_id=operation)
                return data
        except requests.Timeout:
            record('llm_request', stage=stage, status='error', operation_id=operation)
            message = ('Истекло время ожидания генерации Ollama. Первая загрузка модели может быть медленной; проверьте память и журнал сервера.'
                       if path == '/api/generate' else 'Истекло время ожидания Ollama. Проверьте адрес и доступность сервера.')
            raise ValueError(message) from None
        except requests.HTTPError as exc:
            record('llm_request', stage=stage, status='error', operation_id=operation)
            code = exc.response.status_code
            if code == 404 and path in {'/api/show', '/api/generate'}:
                raise ValueError('Модель отсутствует на сервере Ollama. Обновите список моделей.') from None
            if path == '/api/generate':
                raise ValueError(f'Ollama не выполнила генерацию (HTTP {code}). Проверьте память и журнал сервера.') from None
            raise ValueError(f'Ошибка API Ollama (HTTP {code}). Проверьте адрес сервера.') from None
        except (ValueError, TypeError):
            # requests.JSONDecodeError also inherits RequestException: malformed JSON
            # must be handled before the generic connection failure below.
            record('llm_request', stage=stage, status='error', operation_id=operation)
            raise ValueError('Сервер Ollama вернул некорректный ответ.') from None
        except requests.RequestException:
            record('llm_request', stage=stage, status='error', operation_id=operation)
            raise ValueError('Ошибка подключения к Ollama. Проверьте адрес и запустите сервер самостоятельно.') from None

    def connection(self):
        version = self.request('/api/version').get('version')
        if not isinstance(version, str) or not version.strip():
            raise ValueError('Сервер не вернул версию Ollama.')
        return version

    def models(self):
        models = self.request('/api/tags').get('models')
        if not isinstance(models, list) or any(not isinstance(m, dict) or
                not isinstance(m.get('name'), str) or not m['name'].strip() for m in models):
            raise ValueError('Сервер вернул некорректный список моделей Ollama.')
        return [{'id': m['name'], 'title': m['name'], 'bytes': m.get('size', 0)} for m in models]

    def validate_text_model(self, model):
        capabilities = self.request('/api/show', {'model': model}).get('capabilities')
        if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
            raise ValueError('Сервер вернул некорректные возможности модели Ollama')
        if 'completion' not in capabilities:
            raise ValueError('Эта модель не поддерживает генерацию текста; выберите языковую модель')

    def verify(self, model, *, check_cancel=lambda: None):
        operation = uuid.uuid4().hex
        record('llm_verification', stage='generation', status='started', operation_id=operation)
        try:
            check_cancel()
            require_model(self, model)
            check_cancel()
            self.validate_text_model(model)
            check_cancel()
            result = self.request('/api/generate', {'model': model, 'prompt': 'Reply with one word: ready.',
                                  'stream': False, 'think': False, 'options': {'num_predict': 32}}, timeout=180)
            check_cancel()
            if result.get('done') is not True or not isinstance(result.get('response'), str) or not result['response'].strip():
                raise ValueError('Модель не вернула текст при проверке генерации.')
        except Exception:
            record('llm_verification', stage='generation', status='error', operation_id=operation)
            raise
        record('llm_verification', stage='generation', status='done', operation_id=operation)
