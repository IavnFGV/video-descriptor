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
            raise ValueError('Истекло время ожидания Ollama. Проверьте сервер и доступную память.') from None
        except requests.RequestException:
            record('llm_request', stage=stage, status='error', operation_id=operation)
            raise ValueError('Ошибка подключения к Ollama. Проверьте адрес и запустите сервер самостоятельно.') from None
        except (ValueError, TypeError):
            record('llm_request', stage=stage, status='error', operation_id=operation)
            raise ValueError('Сервер Ollama вернул некорректный ответ.') from None

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
        if not isinstance(capabilities, list) or 'completion' not in capabilities:
            raise ValueError('Эта модель не поддерживает генерацию текста; выберите языковую модель')

    def verify(self, model):
        operation = uuid.uuid4().hex
        record('llm_verification', stage='generation', status='started', operation_id=operation)
        try:
            require_model(self, model)
            result = self.request('/api/generate', {'model': model, 'prompt': 'Reply with one word: ready.',
                                  'stream': False, 'think': False, 'options': {'num_predict': 32}}, timeout=180)
            if result.get('done') is not True or not isinstance(result.get('response'), str) or not result['response'].strip():
                raise ValueError('Модель не вернула текст при проверке генерации.')
        except Exception:
            record('llm_verification', stage='generation', status='error', operation_id=operation)
            raise
        record('llm_verification', stage='generation', status='done', operation_id=operation)
