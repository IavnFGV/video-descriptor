"""Selected Ollama endpoint shared by desktop, planning and immutable job snapshots."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from .jobs import read_json

DEFAULT_URL = 'http://127.0.0.1:11434'
MODES = {'existing', 'service', 'managed'}


def loopback_url(value):
    if not isinstance(value, str) or not value or value != value.strip() or any(c.isspace() for c in value) or '\\' in value:
        raise ValueError('Укажите локальный HTTP-адрес Ollama, например http://127.0.0.1:11434')
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        if (parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}
                or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
            raise ValueError
    except ValueError:
        raise ValueError('Поддерживается только HTTP на localhost, 127.0.0.1 или [::1], без логина, пути и параметров') from None
    host = '[::1]' if parsed.hostname == '::1' else parsed.hostname
    return 'http://' + host + (':' + str(port) if port is not None else '')


def selected(value):
    url = loopback_url(value.get('ollama_url', DEFAULT_URL))
    mode = value.get('ollama_mode')
    if mode not in MODES:
        # Legacy non-default endpoints remain external. Never infer ownership from a port.
        mode = 'existing' if url == DEFAULT_URL else 'service'
    return {'mode': mode, 'url': url, 'ownership': 'managed' if mode == 'managed' else 'external'}


def workspace_file(root):
    return Path(root) / '.devcontainer/ollama-connection.json'


def base_url(root):
    return (os.getenv('VIDEO_DESCRIPTOR_JOB_OLLAMA_URL')
            or read_json(workspace_file(root), {}).get('url')
            or os.getenv('OLLAMA_BASE_URL', 'http://host.docker.internal:11434'))


def job_environment(url):
    return {**os.environ, 'OLLAMA_BASE_URL': url, 'VIDEO_DESCRIPTOR_JOB_OLLAMA_URL': url}
