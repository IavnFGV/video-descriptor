"""Explicit connection checks; never return upstream bodies or credentials."""
import os

import requests

from .translation_settings import load


def connections(root):
    settings = load(root)
    result = {}
    base = os.getenv('OLLAMA_BASE_URL', 'http://host.docker.internal:11434').rstrip('/')
    try:
        response = requests.get(base + '/api/tags', timeout=(2, 3))
        response.raise_for_status()
        names = [item['name'] for item in response.json()['models']]
        selected = settings.get('ollama_model') or os.getenv('OLLAMA_MODEL', 'qwen3.5:9b')
        result['ollama'] = {'status': 'ok' if selected in names else 'missing_model',
                            'message': 'Ollama доступна' if selected in names else
                            'Установите выбранную модель в Ollama или измените модель в настройках'}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        result['ollama'] = {'status': 'unavailable', 'message':
                            'Ollama недоступна. Запустите её на хосте; проверьте OLLAMA_BASE_URL и firewall'}
    if not settings['api_key']:
        result['gemini'] = {'status': 'missing_key', 'message': 'Добавьте ключ Gemini в Подключениях'}
    else:
        from .gemini import BASE
        try:
            response = requests.get(BASE + '/models', headers={'x-goog-api-key': settings['api_key']},
                                    timeout=(2, 5))
            status = 'ok' if response.ok else ('invalid_key' if response.status_code in (400, 401, 403)
                                             else 'unavailable')
            result['gemini'] = {'status': status, 'message': 'Gemini доступна' if response.ok else
                                f'Gemini HTTP {response.status_code}: проверьте ключ, права API и квоту'}
        except requests.RequestException:
            result['gemini'] = {'status': 'unavailable', 'message': 'Gemini: нет соединения с API'}
    return result
