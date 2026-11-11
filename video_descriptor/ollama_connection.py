"""Selected Ollama endpoint shared by desktop, planning and immutable job snapshots."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from .jobs import read_json

DEFAULT_URL = 'http://127.0.0.1:11434'


def endpoint_url(value):
    if not isinstance(value, str) or not value or value != value.strip() or any(c.isspace() for c in value) or "\\" in value:
        raise ValueError('Укажите HTTP(S)-адрес сервера Ollama')
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in {'', '/'} or (port is not None and not 1 <= port <= 65535)):
            raise ValueError
    except ValueError:
        raise ValueError('Нужен HTTP(S)-адрес без логина, пути и параметров') from None
    return value.rstrip('/')


def selected(value):
    return {'url': endpoint_url(value.get('ollama_url', DEFAULT_URL)), 'ownership': 'external'}


def workspace_file(root):
    return Path(root) / '.devcontainer/ollama-connection.json'


def base_url(root):
    return (os.getenv('VIDEO_DESCRIPTOR_JOB_OLLAMA_URL')
            or read_json(workspace_file(root), {}).get('url')
            or os.getenv('OLLAMA_BASE_URL', DEFAULT_URL))


def job_environment(url):
    return {**os.environ, 'OLLAMA_BASE_URL': url, 'VIDEO_DESCRIPTOR_JOB_OLLAMA_URL': url}
