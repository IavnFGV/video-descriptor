"""Run bundled CPU inference in a fresh directory with isolated user/component state."""
import argparse
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

from verify_release import extract_zip, progress


def verify(archive, output):
    folder = Path(tempfile.mkdtemp(prefix='vd-domestic-'))
    with zipfile.ZipFile(archive) as source:
        extract_zip(source, folder)
    progress('Проверяем профиль пакета: встроенные модели Whisper и диаризации')
    manifest = json.loads((folder / 'release-manifest.json').read_text())
    assert manifest['profile'] == 'domestic' and manifest['whisper_weights_included']
    here = folder / 'windows-app'
    local_data = folder / 'test-user'
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('PYTHON', 'HF_', 'WHISPER', 'VIDEO_DESCRIPTOR'))}
    env.update(LOCALAPPDATA=str(local_data), PATH=str(Path(os.environ['SystemRoot']) / 'System32'),
               PYTHONUTF8='1', VIDEO_DESCRIPTOR_VERIFY_PROGRESS='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HF_HUB_DISABLE_TELEMETRY='1', OPENVINO_TELEMETRY='0', DO_NOT_TRACK='1')
    command = [str(folder / 'python/python.exe'), '-X', 'utf8', str(here / 'domestic_setup.py')]
    with (folder / 'verification.log').open('wb') as log:
        progress('Запускаем автономную подготовку: контрольные суммы, WebView2, реальное CPU-распознавание и диаризация; лимит 20 мин')
        subprocess.run(command, cwd=folder, env=env, stderr=log, check=True, timeout=1200)
        progress('Подготовка завершена; проверяем результаты CPU inference и изоляцию путей')
        settings = json.loads((here / 'config.local.json').read_text())
        assert Path(settings['diarization_python']).is_relative_to(folder)
        assert Path(settings['whisper_model_directory']).is_relative_to(folder)
        assert settings['diarization_device'] == settings['diarization_requested_device'] == 'cpu'
        speech = json.loads((here / 'runtime/domestic-speech.json').read_text())
        assert speech['segments'] > 0 and speech['engine']['device'] == 'CPU'
        state = json.loads((local_data / 'VideoDescriptor/ai-components/state.json').read_text())
        diarization = state['diarization']
        assert diarization['state'] == 'ready' and diarization['proof']['turns']
        assert diarization['proof']['device'] == 'cpu'
        assert json.loads((here / 'runtime/setup-state.json').read_text())['completed']
        saved = (here / 'config.local.json').read_bytes()
        progress('PASS: CPU Whisper и диаризация; повторяем подготовку для проверки повторного запуска, лимит 120 с')
        subprocess.run(command, cwd=folder, env=env, stderr=log, check=True, timeout=120)
        assert (here / 'config.local.json').read_bytes() == saved
    progress('PASS: повторная подготовка сохранила настройки; сохраняем отчёт')
    result = {'status': 'PASS', 'folder': str(folder), 'version': manifest['version'],
              'cpu_whisper_inference': True, 'cpu_diarization_inference': True,
              'idempotent_setup': True, 'isolated_user_state': True,
              'limits': ['Current Windows host; not a clean VM installer lifecycle',
                         'HF offline flags; not a network-isolated guest', 'NPU/GPU not tested']}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    verify(args.archive, args.output)
