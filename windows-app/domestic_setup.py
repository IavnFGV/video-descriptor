"""Installer/portable preparation for bundled assets; no downloads or package installs."""
import contextlib
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))


def progress(message):
    if os.environ.get('VIDEO_DESCRIPTOR_VERIFY_PROGRESS') == '1':
        print(time.strftime('[%H:%M:%S] ') + message, file=sys.__stdout__, flush=True)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.domestic.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def defaults(here, existing):
    """Only fill missing settings; upgrades preserve device choices and user models."""
    values = dict(existing)
    bundled = here / 'domestic'
    additions = {'whisper_model_directory': str(bundled / 'whisper'),
                 'diarization_model_directory': str(bundled / 'diarization'),
                 'diarization_python': str(bundled / 'python/python.exe')}
    for key, value in additions.items():
        if not values.get(key):
            values[key] = value
    if not existing.get('diarization_python'):
        values.update(diarization_device='cpu', diarization_requested_device='cpu')
    return values


def main():
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                      OPENVINO_TELEMETRY='0', DO_NOT_TRACK='1')
    manifest = json.loads((ROOT / 'release-manifest.json').read_text())
    profile = manifest['domestic']
    local = HERE / 'config.local.json'
    existing = json.loads(local.read_text(encoding='utf-8')) if local.exists() else {}
    marker = HERE / 'runtime/domestic-setup.json'
    previous = json.loads(marker.read_text()) if marker.exists() else {}
    same_validation = bool(manifest.get('component_validation_key')) and previous.get('validation_key') == manifest['component_validation_key']
    same_version = not manifest.get('component_validation_key') and previous.get('version') == manifest['version']
    if (same_version or same_validation) and previous.get('root') == str(ROOT) and existing:
        progress('PASS: подготовка этой версии уже выполнена, повторный запуск не меняет настройки')
        return
    progress('Проверяем SHA256 встроенных моделей и runtime')
    # ZIP/Inno extraction checks container integrity; wheels were hash-locked at build.
    # Recheck models and the Python executable boundary without reopening thousands
    # of site-packages files (very slow with Windows on-access scanning).
    for entry in manifest['files']:
        if entry['path'].startswith('windows-app/domestic/') and not entry['path'].startswith(
                'windows-app/domestic/python/Lib/'):
            import hashlib
            with (ROOT / entry['path']).open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
                    raise ValueError('Bundled file checksum mismatch: ' + entry['path'])
    progress('PASS: SHA256; проверяем встроенный WebView2')
    settings = defaults(HERE, existing)
    runtime = HERE / 'webview2-runtime'
    if not (runtime / 'msedgewebview2.exe').is_file():
        powershell = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                        '-File', str(HERE / 'Ensure-WebView2.ps1'), '-Mode', 'Install',
                        '-LoaderPath', str(HERE / 'desktop-sdk/WebView2Loader.dll'),
                        '-InstallerPath', str(HERE / 'domestic/WebView2Runtime.x64.cab'),
                        '-RuntimeDirectory', str(runtime), '-ExpectedSha256', profile['webview_sha256'],
                        '-RuntimeVersion', profile['webview_version'],
                        '-LogPath', str(HERE / 'domestic-webview.jsonl')], check=True,
                       stdout=sys.stdout, stderr=sys.stderr)
    progress('PASS: WebView2; подготавливаем проверки моделей')
    # Write no build-machine path; installed location is known only at this point.
    write_json(local, settings)
    import app
    from component_manager import ComponentManager
    from compute import ComputeManager
    from setup_service import SetupService
    manager = ComputeManager(app.config(), HERE)
    setup = SetupService(manager, HERE)
    components = ComponentManager(setup)
    # Existing external models/environments and explicit devices are left intact.
    speech_checked = settings['whisper_model_directory'] == str(HERE / 'domestic/whisper')
    if speech_checked:
        progress('CPU Whisper: загружаем модель и распознаём контрольный WAV, лимит 600 с')
        setup.apply(settings['whisper_model_directory'])
        subprocess.run([sys.executable, '-X', 'utf8', str(HERE / 'whisper_worker.py'),
                        '--model', settings['whisper_model_directory'], '--device', 'CPU',
                        '--probe', str(HERE / 'samples/speech-check.wav'),
                        '--output', str(HERE / 'runtime/domestic-speech.json')], check=True, timeout=600,
                       stdout=sys.stdout, stderr=sys.stderr)
        progress('PASS: контрольный WAV распознан на CPU')
    diarization_checked = settings['diarization_python'] == str(HERE / 'domestic/python/python.exe')
    if diarization_checked:
        progress('CPU диаризация: загружаем модель и проверяем разделение контрольной записи')
        updated = time.monotonic()
        components.action('diarization', {'action': 'check', 'device': settings.get('diarization_requested_device', 'cpu'),
                                        'resume': None})
        while components.active:
            if time.monotonic() - updated >= 10:
                progress('CPU диаризация: проверка продолжается; ожидаем завершения модели')
                updated = time.monotonic()
            time.sleep(.2)
        item = next(item for item in components.snapshot()['components'] if item['id'] == 'diarization')
        if item['state'] != 'ready':
            raise RuntimeError(item.get('message', 'Bundled diarization check failed'))
        progress('PASS: CPU диаризация готова')
    if speech_checked and diarization_checked:
        setup.complete()
    write_json(marker, {'version': manifest['version'], 'root': str(ROOT), 'profile': 'domestic',
                        'speech_checked': speech_checked, 'diarization_checked': diarization_checked,
                        'validation_key': manifest.get('component_validation_key')})


if __name__ == '__main__':
    log = HERE / 'runtime/domestic-setup.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a', encoding='utf-8') as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        try:
            main()
        except Exception:  # noqa: BLE001 — installer boundary; retain diagnostics for hidden setup.
            traceback.print_exc()
            raise SystemExit(1) from None
