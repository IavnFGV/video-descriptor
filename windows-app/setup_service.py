"""First-run setup imports existing verified weights; no downloads or executable paths."""
import json
import os
import subprocess
from pathlib import Path

import requests

from scripts.whisper_npu_server import model_digest
from video_descriptor import translation_settings
from video_descriptor.action_history import record
from video_descriptor.jobs import read_json, write_json


def ollama_request(value, endpoint, body=None):
    with requests.Session() as session:
        session.trust_env = False
        url = value.get('ollama_url', 'http://127.0.0.1:11434') + endpoint
        response = session.get(url, timeout=5) if body is None else session.post(url, json=body, timeout=5)
        response.raise_for_status()
        return response.json()


def ollama_status(value):
    settings = translation_settings.load(value['workspace'])
    selected = settings.get('ollama_model') or value.get('ollama_model', '')
    try:
        data = ollama_request(value, '/api/tags')
        models = [{'name': item['name'], 'bytes': item.get('size', 0)} for item in data['models']]
        present = selected in {item['name'] for item in models}
        return {'ready': present, 'service_ready': True, 'selected': selected, 'models': models,
                'message': 'Модель установлена; генерация проверяется при обработке' if present else
                           'Выберите установленную модель для перевода'}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return {'ready': False, 'service_ready': False, 'selected': selected, 'models': [],
                'message': 'Запустите установленную Ollama и обновите список. Автоустановка пока не подключена.'}


def validate_ollama_model(value, model):
    status = ollama_status(value)
    if not isinstance(model, str) or model not in {item['name'] for item in status['models']}:
        raise ValueError('Выберите модель из списка установленной Ollama')
    try:
        details = ollama_request(value, '/api/show', {'model': model})
        if 'completion' not in details.get('capabilities', []):
            raise ValueError('Эта модель не поддерживает генерацию текста; выберите языковую модель')
    except (requests.RequestException, TypeError) as exc:
        raise ValueError('Не удалось проверить возможности модели Ollama') from exc


def select_ollama(value, model):
    validate_ollama_model(value, model)
    translation_settings.save(value['workspace'], {'provider': 'ollama', 'ollama_model': model})
    record('translation_model_configured', stage='translation', status='configured')
    return {'selected': model, 'provider': 'ollama', 'configured': True}


def inspect_model(value, here):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ValueError('Выберите папку с моделью Whisper small FP16')
    path = Path(value.strip())
    if not path.is_absolute() or path.anchor.startswith('\\\\'):
        raise ValueError('Выберите локальную папку по полному пути')
    path = path.resolve()
    required = ['config.json', 'generation_config.json', 'preprocessor_config.json',
                'tokenizer_config.json', 'tokenizer.json']
    required += [f'openvino_{name}.{extension}' for name in
                 ('encoder_model', 'decoder_model', 'tokenizer', 'detokenizer')
                 for extension in ('xml', 'bin')]
    missing = [name for name in required if not (path / name).is_file() or (path / name).stat().st_size == 0]
    if missing:
        raise ValueError('В папке не хватает файлов: ' + ', '.join(missing))
    config = read_json(path / 'config.json', {})
    if not isinstance(config, dict) or config.get('encoder_layers') != 12 or config.get('vocab_size') != 51865:
        raise ValueError('Нужна многоязычная модель Whisper small в формате OpenVINO FP16')
    expected = read_json(Path(here) / 'component-manifest.json')['whisper_model']['engine_digest_sha256']
    digest = model_digest(path)
    if digest != expected:
        raise ValueError('Файлы отличаются от проверенной Whisper small FP16. Выберите исходную модель или восстановите её файлы')
    return {'path': str(path), 'model': 'Whisper small FP16', 'sha256': digest,
            'bytes': sum((path / name).stat().st_size for name in required), 'verified': True}


def choose_folder():
    if os.name != 'nt':
        raise ValueError('Укажите полный путь к папке модели')
    script = """Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Select the existing OpenVINO Whisper small FP16 model folder'
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    [Console]::Write($dialog.SelectedPath)
}
$dialog.Dispose()
"""
    result = subprocess.run(['powershell.exe', '-NoProfile', '-STA', '-Command', script],
                            capture_output=True, text=True, encoding='utf-8-sig', timeout=180,
                            check=True, creationflags=0x08000000)
    return result.stdout.strip()


class SetupService:
    def __init__(self, manager, here):
        self.manager = manager
        self.here = Path(here)

    def snapshot(self):
        model = self.manager.model
        present = (model / 'config.json').is_file()
        return {'model_path': str(model), 'model_present': present,
                'verified': present and bool(self.manager.value.get('whisper_model_sha256')),
                'model_name': 'Whisper small FP16', 'downloads': False}

    def apply(self, value):
        verified = inspect_model(value, self.here)
        manager = self.manager
        with manager._lock:
            active = Path(manager.value['workspace']) / 'output/jobs'
            if manager.preparing or any(read_json(p, {}).get('status') in {'queued', 'running'} for p in active.glob('*/job.json')):
                raise RuntimeError('Дождитесь завершения обработки или подготовки модели')
            local_file = self.here / 'config.local.json'
            local = json.loads(local_file.read_text(encoding='utf-8')) if local_file.exists() else {}
            if not isinstance(local, dict):
                raise TypeError('Локальные настройки повреждены; существующий файл сохранён')
            local.update(whisper_model_directory=verified['path'], whisper_model_sha256=verified['sha256'])
            changed = {**manager.value, 'whisper_model_directory': verified['path'],
                       'whisper_model_sha256': verified['sha256']}
            replacement = type(manager)(changed, manager.here)
            write_json(local_file, local)
            manager.value.update(changed)
            manager.python, manager.model, manager.backends = replacement.python, replacement.model, replacement.backends
            manager._inventory = None
            manager.failed.clear()
            manager.last_error = ''
        record('model_configured', stage='speech', model_sha256=verified['sha256'])
        return verified
