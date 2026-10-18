"""First-run configuration and explicit preparation using existing backend management."""
import io
import json
import os
import shutil
import subprocess
import threading
import wave
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
        compatible = present and ollama_completion(value, selected)
        return {'ready': compatible, 'model_present': present, 'compatible': compatible, 'detected': bool(shutil.which('ollama')), 'service_ready': True, 'selected': selected, 'models': models,
                'message': 'Языковая модель настроена; генерация проверяется при обработке' if compatible else
                           'Выберите установленную модель для перевода'}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return {'ready': False, 'detected': bool(shutil.which('ollama')), 'service_ready': False, 'selected': selected, 'models': [],
                'message': 'Запустите установленную Ollama и обновите список. Автоустановка пока не подключена.'}



def ollama_completion(value, model):
    try:
        details = ollama_request(value, '/api/show', {'model': model})
        return isinstance(details, dict) and 'completion' in details.get('capabilities', [])
    except (requests.RequestException, ValueError, TypeError):
        return False


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


def select_ollama(value, model, task="translation"):
    if task not in {"translation", "notes"}:
        raise ValueError("Выберите перевод или конспект")
    validate_ollama_model(value, model)
    if task == 'translation':
        translation_settings.save(value['workspace'], {'provider': 'ollama', 'ollama_model': model})
    else:
        path = Path(value['workspace']) / '.devcontainer/notes-settings.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, {'ollama_model': model})
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
        self.state = {'status': 'idle', 'message': ''}
        self.hardware = None

    def snapshot(self):
        model = self.manager.model
        present = (model / 'config.json').is_file()
        return {'model_path': str(model), 'model_present': present,
                'verified': present and bool(self.manager.value.get('whisper_model_sha256')),
                'model_name': 'Whisper small FP16', 'downloads': True,
                'download': self.profile(), 'operation': dict(self.state),
                'completed': read_json(self.here / 'runtime/setup-state.json', {}).get('completed', False)}

    def apply(self, value, *, downloading=False):
        verified = inspect_model(value, self.here)
        manager = self.manager
        with manager._lock:
            active = Path(manager.value['workspace']) / 'output/jobs'
            if (manager.operation and not downloading) or manager.preparing or any(read_json(p, {}).get('status') in {'queued', 'running'} for p in active.glob('*/job.json')):
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


    def profile(self):
        profile = read_json(self.here / 'component-manifest.json')['whisper_model']
        return {key: profile.get(key) for key in ('source', 'revision', 'download_bytes')}

    def guard(self):
        manager = self.manager
        active = Path(manager.value['workspace']) / 'output/jobs'
        if manager.preparing or manager.operation or any(
                read_json(p, {}).get('status') in {'queued', 'running'} for p in active.glob('*/job.json')):
            raise RuntimeError('Дождитесь завершения обработки или настройки')

    def start(self, kind, work):
        with self.manager._lock:
            self.guard()
            self.manager.operation = kind
            self.state = {'status': 'running', 'kind': kind, 'message': 'Выполняем…'}

        def run():
            try:
                result = work()
                with self.manager._lock:
                    self.state = {'status': 'done', 'kind': kind, 'message': 'Готово', 'result': result}
            except (OSError, ValueError, TypeError, RuntimeError, requests.RequestException) as exc:
                with self.manager._lock:
                    self.state = {'status': 'error', 'kind': kind,
                                  'message': str(exc) if not isinstance(exc, requests.RequestException) else
                                  'Ошибка сети. Повторите действие; проверенные файлы сохранены.'}
            finally:
                with self.manager._lock:
                    self.manager.operation = None
        threading.Thread(target=run, name='setup-' + kind, daemon=True).start()
        return {'status': 'running', 'kind': kind}

    def download(self, confirmed):
        if confirmed is not True:
            raise ValueError('Подтвердите загрузку модели')

        def work():
            from model_download import download_profile
            profile = read_json(self.here / 'component-manifest.json')['whisper_model']

            def progress(done, total, name):
                with self.manager._lock:
                    self.state.update(bytes=done, total=total, message=name)
            staging, target = download_profile(profile, self.here / 'runtime/models', progress)
            inspect_model(str(staging), self.here)
            if target.exists():
                # Never remove or overwrite an existing model, even if damaged.
                inspect_model(str(target), self.here)
            else:
                staging.rename(target)
            return self.apply(str(target), downloading=True)
        return self.start('download', work)

    def probe(self, audio):
        try:
            with wave.open(io.BytesIO(audio), 'rb') as stream:
                if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
                    raise ValueError('Нужен WAV mono PCM16, 16000 Гц, до 15 секунд')
                frames = stream.getnframes()
                if not 0 < frames <= 15 * 16000 or len(stream.readframes(frames)) != frames * 2:
                    raise ValueError('Выберите неповреждённый WAV до 15 секунд')
        except (wave.Error, EOFError) as exc:
            raise ValueError('Нужен WAV mono PCM16, 16000 Гц, до 15 секунд') from exc

        def work():
            plan = self.manager.make_plan(self.manager.settings()['speech_device'])
            backend = self.manager.backends[plan['selected']]
            with requests.Session() as session:
                session.trust_env = False
                response = session.post(backend['url'] + '/transcribe', data=audio,
                                        headers={'X-Whisper-Model': 'small', 'X-Language': 'auto'}, timeout=(5, 180))
                response.raise_for_status()
                data = response.json()
            if not isinstance(data.get('segments'), list):
                raise TypeError('Обработчик вернул некорректный результат')
            return {'device': plan['selected'], 'segments': len(data['segments']),
                    'message': 'Проверка распознавания выполнена' if data['segments'] else
                               'Обработчик ответил, речь не обнаружена. Выберите фрагмент с речью.'}
        return self.start('probe', work)

    def complete(self):
        with self.manager._lock:
            self.guard()
            path = self.here / 'runtime/setup-state.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, {'completed': True})
        return {'completed': True}

    def diagnostics(self):
        from video_descriptor import translation_settings
        inventory = self.manager.inventory()
        settings = translation_settings.public(translation_settings.load(self.manager.value['workspace']))
        ollama = ollama_status(self.manager.value)
        notes = read_json(Path(self.manager.value['workspace']) / '.devcontainer/notes-settings.json', {}).get('ollama_model', '')
        text_ready = ollama['ready']
        if self.hardware is None:
            self.hardware = hardware_inventory()
        return {'hardware': self.hardware, 'inventory': inventory, 'runtime_python': str(self.manager.python),
                'runtime_present': self.manager.python.is_file(), 'gemini': settings,
                'ocr': {'detected': bool(shutil.which('tesseract')), 'ready': False,
                        'message': 'Tesseract найден; языки и Windows pipeline не проверены' if shutil.which('tesseract') else
                                   'Tesseract не найден; необязательный компонент'},
                'translation': {'state': 'configured' if text_ready or settings['has_key'] else 'setup_required',
                                'message': 'Модель/ключ настроены; генерация выполняется по запросу'},
                'notes': {'state': 'configured' if notes and notes in {m['name'] for m in ollama['models']} and ollama_completion(self.manager.value, notes) else 'setup_required', 'selected': notes,
                          'message': 'Выберите модель Ollama для конспекта'},
                'diarization': {'state': 'unavailable', 'message': 'Windows диаризация не проверена; можно пропустить'}}

    def gemini(self, changes):
        from video_descriptor import gemini
        root = self.manager.value['workspace']
        with self.manager._lock:
            if changes.get('check') is True:
                settings = translation_settings.load(root)
            else:
                return translation_settings.save(root, {**changes, 'provider': 'gemini'})
        try:
            models = gemini.models(settings['api_key'])
        except (requests.RequestException, ValueError, TypeError, KeyError):
            raise ValueError('Gemini недоступен: проверьте ключ, сеть, права и квоты. Данные записи не отправлялись.') from None
        return {'models': models, 'available': settings['model'] in {item['id'] for item in models},
                'message': 'Получен список моделей. Генерация и оплачиваемая квота не проверялись.'}


def hardware_inventory():
    """Read-only PnP inventory, independent of OpenVINO imports and inference."""
    result = {'cpu': os.environ.get('PROCESSOR_IDENTIFIER', 'CPU'), 'intel_gpu': [], 'intel_npu': []}
    if os.name != 'nt':
        return result
    script = """$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$gpu=@(Get-CimInstance Win32_VideoController | Where-Object {$_.Name -match 'Intel'} | ForEach-Object {$_.Name})
$npu=@(Get-CimInstance Win32_PnPEntity | Where-Object {$_.Name -match 'Intel.*(AI Boost|NPU)'} | ForEach-Object {$_.Name})
@{intel_gpu=$gpu;intel_npu=$npu} | ConvertTo-Json -Compress
"""
    try:
        output = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, text=True, encoding='utf-8-sig', check=True,
                                timeout=15, creationflags=0x08000000)
        result.update(json.loads(output.stdout))
    except (OSError, ValueError, subprocess.SubprocessError):
        result['message'] = 'Системный список устройств недоступен; см. устройства OpenVINO'
    return result
