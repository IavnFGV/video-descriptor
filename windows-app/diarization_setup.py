"""Select and verify a native diarization runtime before changing application settings."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from video_descriptor.platform_support import windows_powershell, windows_shell_environment


def detect_adapters():
    if os.name != 'nt':
        return []
    command = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
               "ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_VideoController | "
               "ForEach-Object {$_.Name})")
    result = subprocess.run([windows_powershell(), '-NoProfile', '-Command', command], check=True,
                            capture_output=True, encoding='utf-8-sig', timeout=30, env=windows_shell_environment(), creationflags=0x08000000)
    adapters = json.loads(result.stdout)
    return adapters if isinstance(adapters, list) else [adapters]


def choose_device(requested, adapters):
    if requested in {'cpu', 'xpu'}:
        return requested
    if requested != 'auto':
        raise ValueError('Выберите auto, cpu или xpu.')
    return 'xpu' if any('intel' in name.lower() and 'basic' not in name.lower() for name in adapters) else 'cpu'


def environment(device):
    name = '.venv-diarization-xpu' if device == 'xpu' else '.venv-diarization'
    return ROOT / name / 'Scripts/python.exe'


def runtime_in_use(python):
    local = HERE / 'config.local.json'
    settings = json.loads(local.read_text(encoding='utf-8')) if local.exists() else {}
    workspace = (HERE / settings.get('workspace', 'runtime/workspace')).resolve()
    for path in (workspace / 'output/jobs').glob('*/job.json'):
        try:
            job = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if (job.get('status') in {'queued', 'running'} and job.get('diarization_python')
                and Path(job['diarization_python']).resolve() == python.resolve()):
            return True
    return False


def run(command):
    print('Подготовка: ' + ('пакеты Python' if 'pip' in command else 'проверка окружения'), flush=True)
    result = subprocess.run(command, stdin=subprocess.DEVNULL, check=False,
                            env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', 'PIP_NO_INPUT': '1'},
                            **({'creationflags': 0x08000000} if os.name == 'nt' else {}))
    if result.returncode:
        raise RuntimeError(f'Подготовка завершилась с кодом {result.returncode}; настройки приложения не изменены.')


def prepare_runtime(device, model, *, install, python=None, probe_audio=None):
    python = Path(python) if python else environment(device)
    if install and runtime_in_use(python):
        print('Окружение используется заданием: пакеты не обновляем, проверяем установленную версию.', flush=True)
        install = False
    if install:
        if not python.is_file():
            if python != environment(device):
                raise ValueError('Указанный Python не найден. Новое окружение автоматически создаётся только в папке приложения.')
            run([sys.executable, '-X', 'utf8', '-m', 'venv', str(python.parent.parent)])
        requirements = ROOT / ('requirements-diarization-xpu.txt' if device == 'xpu' else 'requirements-diarization.txt')
        run([str(python), '-X', 'utf8', '-m', 'pip', 'install', '--disable-pip-version-check',
             '-r', str(requirements)])
        run([str(python), '-X', 'utf8', '-m', 'pip', 'check'])
    if not python.is_file():
        raise ValueError('Окружение диаризации не установлено. Запустите подготовку с -InstallDependencies.')
    worker = HERE / 'diarization_worker.py'
    run([str(python), '-X', 'utf8', str(worker), '--doctor', '--model', str(model), '--device', device])
    directory = HERE / 'runtime/diarization-setup' / device
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / 'probe.json'
    # Always regenerate proof: a previous success cannot validate changed packages or drivers.
    output.unlink(missing_ok=True)
    run([str(python), '-X', 'utf8', str(worker), '--model', str(model), '--device', device,
         '--audio', str(probe_audio or HERE / 'samples/speech-check.wav'),
         '--output', str(output), '--progress', str(directory / 'progress.json')])
    proof = json.loads(output.read_text(encoding='utf-8'))
    if proof.get('device') != device or not proof.get('turns'):
        raise ValueError('Проверка модели не вернула разметку голосов на выбранном устройстве.')
    return python.resolve(), proof


def prepare(requested, model, *, install=False, python=None, probe_audio=None, adapters=None):
    model = Path(model).resolve()
    if not (model / 'config.yaml').is_file():
        raise ValueError('Укажите существующую локальную модель community-1. Модели автоматически не скачиваются.')
    adapters = detect_adapters() if adapters is None and requested == 'auto' else adapters or []
    selected = choose_device(requested, adapters)
    print(f'Диаризация: запрос={requested}; выбран {selected.upper()}; GPU: {", ".join(adapters) or "не обнаружен"}', flush=True)
    warning = ''
    try:
        runtime, proof = prepare_runtime(selected, model, install=install, python=python, probe_audio=probe_audio)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        if requested != 'auto' or selected != 'xpu':
            raise
        warning = 'GPU обнаружен, но проверка PyTorch/pyannote не прошла. Выбран CPU. ' + str(exc)
        print(warning, flush=True)
        selected = 'cpu'
        runtime, proof = prepare_runtime('cpu', model, install=install, probe_audio=probe_audio)
    return {'diarization_python': str(runtime), 'diarization_model_directory': str(model),
            'diarization_device': selected, 'diarization_requested_device': requested,
            'diarization_setup_warning': warning,
            'diarization_probe': {'device': proof['device'], 'inference_seconds': proof['inference_seconds'],
                                  'audio_seconds': proof['duration'], 'speakers': len({r['speaker'] for r in proof['turns']})}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--device', choices=['auto', 'cpu', 'xpu'], default='auto')
    parser.add_argument('--python', type=Path)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--probe-audio', type=Path)
    parser.add_argument('--plan-only', action='store_true')
    args = parser.parse_args()
    if args.plan_only:
        adapters = detect_adapters()
        print(json.dumps({'adapters': adapters, 'device': choose_device(args.device, adapters)}, ensure_ascii=False))
        return
    changed = prepare(args.device, args.model, install=args.install, python=args.python, probe_audio=args.probe_audio)
    local = HERE / 'config.local.json'
    settings = json.loads(local.read_text(encoding='utf-8')) if local.exists() else {}
    settings.update(changed)
    temporary = local.with_suffix('.tmp')
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(local)
    print('Диаризация настроена: ' + changed['diarization_device'].upper() +
          '. Применится после перезапуска приложения при пустой очереди. Текущие задания сохраняют своё устройство.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
