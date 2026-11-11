"""Small external-provider contract. Discovery never performs generation or downloads."""
from typing import Protocol


class Provider(Protocol):
    def connection(self) -> str: ...
    def models(self) -> list[dict]: ...
    def verify(self, model: str) -> None: ...


def require_model(provider: Provider, model: str):
    if not model or model not in {item['id'] for item in provider.models()}:
        raise ValueError('Выбранная модель отсутствует на сервере. Обновите список и выберите модель.')


# A small extension of the existing adapter contract, not a runtime/model manager.
def snapshot(root=None, *, settings=None, provider=None, model=None, endpoint=None, parameters=None):
    from .gemini import BASE
    from .lmstudio import base_url as lm_url
    from .ollama_connection import base_url, endpoint_url
    from .translation_settings import load
    settings = load(root) if settings is None else settings
    provider = provider if provider is not None else settings['provider']
    if provider not in {'ollama', 'lmstudio', 'gemini'}:
        raise ValueError('Неизвестный LLM-провайдер')
    key = {'ollama': 'ollama_model', 'lmstudio': 'lmstudio_model', 'gemini': 'model'}[provider]
    if model is None:
        model = settings.get(key, '')
        # Retain explicit environment configuration for pre-settings CLI installations.
        # A saved empty selection is authoritative and never falls back to it.
        import os
        from pathlib import Path
        if not model and provider == 'ollama' and not (Path(root or Path.cwd()) / '.devcontainer/translation-settings.json').exists():
            model = os.getenv('OLLAMA_MODEL', '')
    import re
    if not isinstance(model, str) or (model and not re.fullmatch(r'[A-Za-z0-9._:/@-]{1,150}', model)):
        raise ValueError('Некорректный идентификатор LLM-модели')
    if provider == 'ollama':
        endpoint = endpoint_url(endpoint if endpoint is not None else base_url(root or '.'))
    elif provider == 'lmstudio':
        endpoint = lm_url(endpoint if endpoint is not None else settings.get('lmstudio_url', 'http://127.0.0.1:1234/v1'))
    else:
        endpoint = BASE
    # Whitelist only generation values; credentials and request content never enter jobs.
    parameters = {key: value for key, value in (parameters or {}).items()
                  if key in {'context_tokens', 'output_tokens', 'temperature', 'thinking', 'num_gpu'}}
    return {'version': 1, 'provider': provider, 'endpoint': endpoint, 'model': model,
            'parameters': parameters}


def environment(value):
    import json
    import os
    env = {key: item for key, item in os.environ.items() if key not in {
        'VIDEO_DESCRIPTOR_LLM_SNAPSHOT', 'VIDEO_DESCRIPTOR_JOB_OLLAMA_URL', 'VIDEO_DESCRIPTOR_JOB_LMSTUDIO_URL'}}
    env['VIDEO_DESCRIPTOR_LLM_SNAPSHOT'] = json.dumps(value)
    if value['provider'] == 'ollama':
        env.update(OLLAMA_BASE_URL=value['endpoint'], VIDEO_DESCRIPTOR_JOB_OLLAMA_URL=value['endpoint'])
    elif value['provider'] == 'lmstudio':
        env['VIDEO_DESCRIPTOR_JOB_LMSTUDIO_URL'] = value['endpoint']
    return env


def selected(root=None, **overrides):
    import json
    import os
    raw = os.getenv('VIDEO_DESCRIPTOR_LLM_SNAPSHOT')
    if raw:
        value = json.loads(raw)
        return snapshot(root, settings={}, provider=value['provider'], model=value['model'],
                        endpoint=value['endpoint'], parameters=value.get('parameters'))
    return snapshot(root, **overrides)


def runtime(value, settings):
    """Attach credentials in memory only, keeping the pinned route authoritative."""
    settings = dict(settings)
    provider, model, endpoint = value['provider'], value['model'], value['endpoint']
    if provider == 'lmstudio':
        from .lmstudio import DEFAULT_URL, base_url
        if settings.get('lmstudio_api_key') and base_url(settings.get('lmstudio_url', DEFAULT_URL)) != endpoint:
            raise ValueError('LM Studio: адрес задания отличается от адреса сохранённого токена; восстановите подключение для продолжения')
        settings.update(lmstudio_url=endpoint, lmstudio_model=model)
    elif provider == 'ollama':
        settings.update(ollama_url=endpoint, ollama_model=model)
    else:
        settings['model'] = model
    settings.update(provider=provider, llm_snapshot=value)
    return settings


def check_model(settings):
    value = settings['llm_snapshot']
    if not value['model']:
        raise ValueError(value['provider'] + ': выберите модель в настройках LLM')
    if value['provider'] == 'ollama':
        from .ollama_provider import Ollama
        try:
            require_model(Ollama(value['endpoint']), value['model'])
        except ValueError as exc:
            raise ValueError('Ollama: ' + str(exc)) from None
    elif value['provider'] == 'lmstudio':
        from .lmstudio import models
        if value['model'] not in {row['id'] for row in models(settings)}:
            raise ValueError('LM Studio: выбранная модель отсутствует на сервере; обновите список моделей')


def generate(settings, prompt, text, log=None, *, context=16384, output_tokens=4096,
             task='construction', schema=None, images=None, metrics=None):
    """Dispatch to existing transports; Ollama keeps its streaming/retry lifecycle."""
    value = settings['llm_snapshot']
    provider, model, endpoint = value['provider'], value['model'], value['endpoint']
    if not model:
        raise ValueError(provider + ': выберите модель в настройках LLM')
    if provider == 'ollama':
        from .notes import chat_json
        return chat_json(prompt, text, schema, model, endpoint, log, context=context,
                         output_limit=output_tokens, task=task, images=images, metrics=metrics)
    if provider == 'lmstudio':
        from .lmstudio import generate as request
        kwargs = {'output_tokens': output_tokens, 'task': task}
        if schema is not None or images:
            kwargs.update(schema=schema, images=images)
        return request(settings, model, prompt, text, log, **kwargs)
    if provider == 'gemini':
        from .gemini import translate
        return translate(prompt, text, settings, log, output_tokens=output_tokens,
                         task=task, schema=schema, images=images, effective_prompt=True)
    raise ValueError('Неизвестный LLM-провайдер')
