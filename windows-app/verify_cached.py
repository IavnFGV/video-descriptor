"""Exercise the complete cached installer in an isolated registration and test copy."""
import argparse
import json
import os
import platform
import re
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from build_release import HERE, sha256
from component_cache import digest
from verify_release import extract_zip, progress, smoke, stop_owned_processes


def application_registration(app_id):
    import winreg
    result = {}
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            path = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + app_id + '_is1'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | view) as key:
                values = []
                index = 0
                while True:
                    try:
                        values.append(winreg.EnumValue(key, index))
                        index += 1
                    except OSError:
                        break
                result[view] = values
        except FileNotFoundError:
            pass
    return result


def execute(command, work, env, timeout=1200):
    progress('Запускаем тестовый установщик; журнал: ' + str(work / 'installer.log'))
    with (work / 'installer.log').open('ab') as log:
        process = subprocess.Popen([str(item) for item in command], env=env, stdout=log, stderr=log,
                                   creationflags=0x08000000)
        started = time.monotonic()
        try:
            while process.poll() is None:
                if time.monotonic() - started > timeout:
                    raise TimeoutError('Isolated cached installer exceeded its time limit')
                time.sleep(2)
                if int(time.monotonic() - started) % 10 < 2:
                    progress(f'Тестовый установщик работает: {int(time.monotonic() - started)} с')
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=20)


def verify(output):
    reference = json.loads((output / 'cache-reference.json').read_text(encoding='utf-8'))
    bundle = Path(reference['bundle'])
    runtime = bundle / 'components.zip'
    if sha256(runtime) != reference['archive_sha256']:
        raise ValueError('Component archive was modified after compilation')
    with zipfile.ZipFile(output / 'app-payload.zip') as archive:
        manifest = json.loads(archive.read('release-manifest.json'))
    host = digest({'node': platform.node(), 'system': platform.platform(), 'machine': platform.machine()})
    acceptance_key = digest({'backend': manifest['component_validation_key'], 'installer': sha256(HERE / 'installer.iss')})
    proof_file = bundle / ('validation-' + acceptance_key + '-' + host[:12] + '.json')
    proof = json.loads(proof_file.read_text(encoding='utf-8')) if proof_file.exists() else {}
    warm = proof.get('host') == host and proof.get('key') == manifest['component_validation_key'] and proof.get('cpu_inference') is True
    # Inno's archive extractor needs a short target for PyTorch's long header names.
    short_temp = bundle.parent.parent / 't'
    short_temp.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='vc-', dir=short_temp) as temporary:
        work = Path(temporary)
        target = work / 'i'
        (work / 'tmp').mkdir()
        env = dict(os.environ, LOCALAPPDATA=str(work / 'user'), TEMP=str(work / 'tmp'),
                   TMP=str(work / 'tmp'), TMPDIR=str(work / 'tmp'), PYTHONDONTWRITEBYTECODE='1',
                   VIDEO_DESCRIPTOR_VERIFY_PROGRESS='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        production_registration = application_registration('{CA05C8BE-4CF2-4BCA-9B3C-597742FF04D1}')
        try:
            fixture = output / f'VideoDescriptor-{manifest["version"]}-windows-x64-setup.exe'
            progress('Проверяем точный готовый EXE; тестовая регистрация выбирается параметром, без второй компиляции')
            if warm:
                progress('CACHE HIT: CPU-модели уже проверены с этим кодом на этом компьютере; готовим копию компонентов')
                with zipfile.ZipFile(runtime) as archive:
                    extract_zip(archive, target)
                with zipfile.ZipFile(output / 'app-payload.zip') as archive:
                    archive.extractall(target)
                here = target / 'windows-app'
                from domestic_setup import defaults
                here.joinpath('config.local.json').write_text(json.dumps(defaults(here, {})), encoding='utf-8')
                marker = here / 'runtime/domestic-setup.json'
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(json.dumps({'root': str(target.resolve()), 'version': manifest['version'],
                                             'validation_key': manifest['component_validation_key'],
                                             'speech_checked': True, 'diarization_checked': True}), encoding='utf-8')
            else:
                progress('CACHE MISS: проверяем первую автономную установку и реальный CPU inference')
            args = ['/VDLocalTest=1', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/TASKS=', '/NOICONS',
                    '/DIR=' + str(target), '/LOG=' + str(work / 'setup.log')]
            execute([fixture, *args], work, env)
            assert application_registration('{CA05C8BE-4CF2-4BCA-9B3C-597742FF04D1}') == production_registration, 'Real installation registration changed'
            assert application_registration('{683C5737-64A0-47EE-AC74-684EF3CD77B8}'), 'Isolated test registration was not created'
            here = target / 'windows-app'
            if not warm:
                speech = json.loads((here / 'runtime/domestic-speech.json').read_text(encoding='utf-8'))
                state = json.loads((work / 'user/VideoDescriptor/ai-components/state.json').read_text(encoding='utf-8'))
                assert speech['segments'] > 0 and speech['engine']['device'] == 'CPU'
                assert state['diarization']['state'] == 'ready' and state['diarization']['proof']['turns']
                assert state['diarization']['proof']['device'] == 'cpu'
                progress('PASS: первая установка, CPU Whisper и CPU диаризация')
            # Record sizes/timestamps before a real second installer run. The
            # unchanged runtime must not be extracted or rewritten during upgrade.
            component = target / 'windows-app/domestic/whisper/openvino_encoder_model.bin'
            before = component.stat()
            application = here / 'app.py'
            application.write_bytes(application.read_bytes() + b'\n# stale application fixture\n')
            settings = here / 'config.local.json'
            settings_value = json.loads(settings.read_text(encoding='utf-8'))
            settings_value['cached_build_preservation_fixture'] = 'preserve'
            settings.write_text(json.dumps(settings_value), encoding='utf-8')
            saved_settings = settings.read_bytes()
            sentinel = here / 'runtime/workspace/data/preserve.txt'
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text('keep user recording')
            marker = here / 'runtime/domestic-setup.json'
            proof_time = marker.stat().st_mtime_ns
            progress('Проверяем установку поверх старой: модели, настройки и записи должны сохраниться')
            execute([fixture, *args], work, env)
            after = component.stat()
            assert (before.st_mtime_ns, before.st_size) == (after.st_mtime_ns, after.st_size)
            expected_app = next(item['sha256'] for item in manifest['files'] if item['path'] == 'windows-app/app.py')
            assert sha256(application) == expected_app, 'Installer did not replace the old application file'
            assert marker.stat().st_mtime_ns == proof_time, 'Unchanged models were unnecessarily revalidated'
            assert settings.read_bytes() == saved_settings and sentinel.read_text(encoding='utf-8') == 'keep user recording'
            setup_log = (work / 'setup.log').read_text(encoding='utf-8-sig', errors='replace')
            assert 'compatible installed runtime retained without extraction' in setup_log
            progress('PASS: полный установщик обновляет приложение без переустановки и повторного inference компонентов')
            # Use the normal packaged smoke, but restore its deliberately empty
            # model configuration afterwards. Only this disposable copy is touched.
            original_data = os.environ.get('LOCALAPPDATA')
            os.environ['LOCALAPPDATA'] = env['LOCALAPPDATA']
            try:
                smoke(target)
            finally:
                settings.write_bytes(saved_settings)
                if original_data is None:
                    os.environ.pop('LOCALAPPDATA', None)
                else:
                    os.environ['LOCALAPPDATA'] = original_data
            execute([target / 'unins000.exe', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], work, env, 120)
            assert sentinel.read_text(encoding='utf-8') == 'keep user recording' and settings.read_bytes() == saved_settings
            assert not (here / 'app.py').exists()
            assert application_registration('{CA05C8BE-4CF2-4BCA-9B3C-597742FF04D1}') == production_registration, 'Real installation registration changed'
            assert not application_registration('{683C5737-64A0-47EE-AC74-684EF3CD77B8}'), 'Fixture registration remains'
            proof_file.write_text(json.dumps({'host': host, 'key': manifest['component_validation_key'],
                                              'cpu_inference': True}), encoding='utf-8')
            result = {'status': 'PASS', 'version': manifest['version'], 'complete_offline_installer': True,
                      'component_validation': 'cached' if warm else 'fresh_cpu',
                      'isolated_install_upgrade_uninstall': True, 'settings_and_records_preserved': True, 'production_registration_untouched': True,
                      'unchanged_components_not_rewritten': True, 'changed_application_file_replaced': True,
                      'limits': ['Exact produced EXE with isolated test AppId on current host; not a clean Windows VM',
                                 'NPU/GPU inference not tested']}
            (output / 'verification-cached.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            progress('PASS: полный кешируемый установщик и обновление проверены')
        except (OSError, ValueError, AssertionError, subprocess.SubprocessError):
            for log_path in (work / 'setup.log', target / 'windows-app/runtime/domestic-setup.log'):
                if log_path.is_file():
                    text = log_path.read_text(encoding='utf-8-sig', errors='replace')
                    lines = text.splitlines()
                    relevant = []
                    for index, line in enumerate(lines):
                        if any(word in line for word in ('Deleting file:', 'Deleting directory:', 'Extracting file:')):
                            continue
                        if re.search(r'error:|exception|message box|could not|failed|exit code|aborted|cancell', line, re.IGNORECASE):
                            relevant.extend(lines[max(0, index-1):index+4])
                    progress('Диагностика перед удалением временных файлов: ' + '\n'.join(relevant[-80:] or lines[:30]))
            raise
        finally:
            uninstaller = target / 'unins000.exe'
            if uninstaller.is_file():
                try:
                    execute([uninstaller, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], work, env, 120)
                finally:
                    stop_owned_processes(work)
            else:
                stop_owned_processes(work)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    verify(args.output)
