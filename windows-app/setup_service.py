"""First-run setup imports existing verified weights; no downloads or executable paths."""
import json
import os
import subprocess
from pathlib import Path

from scripts.whisper_npu_server import model_digest
from video_descriptor.action_history import record
from video_descriptor.jobs import read_json, write_json


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
