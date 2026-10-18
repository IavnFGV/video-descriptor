"""Explicit ZIP/installer lifecycle smoke test in a fresh directory; no models/network."""
import argparse
import hashlib
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path


def run(command, **kwargs):
    return subprocess.run([str(x) for x in command], check=True, timeout=300, **kwargs)


def free_port():
    with socket.socket() as stream:
        stream.bind(('127.0.0.1', 0))
        return stream.getsockname()[1]


def require_no_registered_install():
    import winreg
    key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{CA05C8BE-4CF2-4BCA-9B3C-597742FF04D1}_is1'
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ | view):
                raise RuntimeError('An installed Video Descriptor is registered. Use a separate Windows user/VM for lifecycle tests.')
        except FileNotFoundError:
            pass


def request(port, path, *, data=None, headers=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=data, headers=headers or {})
    with opener.open(req, timeout=30) as response:
        return json.load(response)


def configure(folder, port):
    settings = folder / 'windows-app/config.local.json'
    settings.write_text(json.dumps({'port': port, 'npu_url': f'http://127.0.0.1:{free_port()}',
                                   'cpu_url': f'http://127.0.0.1:{free_port()}',
                                   'gpu_url': f'http://127.0.0.1:{free_port()}',
                                   'ollama_url': f'http://127.0.0.1:{free_port()}',
                                   'npu_worker_directory': str(folder / 'no-external-benchmark'),
                                   'whisper_model_directory': str(folder / 'no-model')}), encoding='utf-8')
    return settings


def manifest_check(folder):
    manifest = json.loads((folder / 'release-manifest.json').read_text())
    for entry in manifest['files']:
        with (folder / entry['path']).open('rb') as source:
            assert hashlib.file_digest(source, 'sha256').hexdigest() == entry['sha256'], entry['path']
    assert not any((folder / path).exists() for path in ('data', 'output', '.git', '.env', '.venv-windows'))
    return len(manifest['files'])


def start(folder, port):
    python = folder / 'python/python.exe'
    # Remove external Python/CUDA/model paths; only Windows OS tools remain on PATH.
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'HF_', 'WHISPER', 'VIDEO_DESCRIPTOR'))}
    env.update(PATH=str(Path(os.environ['SystemRoot']) / 'System32'), PYTHONUTF8='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
               OPENVINO_TELEMETRY='0', DO_NOT_TRACK='1')
    log = (folder / 'smoke-process.log').open('wb')
    process = subprocess.Popen([str(python), '-X', 'utf8', str(folder / 'windows-app/app.py'), '--no-browser'],
                               cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT,
                               creationflags=0x08000000)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            info = request(port, '/health')
            assert info['app'] == 'video-descriptor-windows'
            # Runner TEMP may use RUNNER~1 while app.resolve() expands the same path.
            assert Path(info['workspace']).samefile(folder / 'windows-app/runtime/workspace')
            return process, log, info['instance']
        except (OSError, ValueError):
            if process.poll() is not None:
                raise RuntimeError('Packaged app failed: ' + (folder / 'smoke-process.log').read_text(errors='replace')) from None
            time.sleep(.25)
    raise TimeoutError('Packaged app did not become ready; see ' + str(folder))


def stop(process, log, port, instance):
    try:
        request(port, '/api/native/stop', data=b'', headers={'X-App-Instance': instance})
        assert process.wait(timeout=20) == 0
    finally:
        log.close()


def smoke(folder):
    port = free_port()
    configure(folder, port)
    process, log, instance = start(folder, port)
    try:
        doctor = request(port, '/api/doctor')
        assert all(doctor['packages'].values()) and doctor['ffmpeg']
        setup = request(port, '/api/setup')
        assert not setup['model_present'] and setup['downloads']
        assert setup['download']['revision'] == '2410d022171ca8a97343182f88eec8807a324db9'
        request(port, '/api/setup/complete', data=b'{}',
                headers={'Content-Type': 'application/json', 'X-App-Instance': instance})
        assert request(port, '/api/setup')['completed']
        compute = request(port, '/api/compute-settings')
        assert compute['selected'] is None
        assert not any(cap['available'] for cap in compute['capabilities'].values())
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/', timeout=5) as page:
            assert 'Устройство распознавания' in page.read().decode()
    finally:
        stop(process, log, port, instance)
    return {'imports': True, 'loopback_ui': True, 'no_system_python_path': True, 'no_model': True, 'graceful_stop': True, 'setup_wizard': True}


def hardware_smoke(folder, video, model):
    """Explicit real CPU/GPU queue test; terminate only workers created by this test copy."""
    from urllib.parse import urlencode

    import psutil
    port = free_port()
    settings = configure(folder, port)
    value = json.loads(settings.read_text())
    value['whisper_model_directory'] = str(model.resolve())
    settings.write_text(json.dumps(value), encoding='utf-8')
    process, log, instance = start(folder, port)
    cases = []
    try:
        for device in ('CPU', 'GPU'):
            request(port, '/api/compute-settings', data=json.dumps({'speech_device': device}).encode(),
                    headers={'Content-Type': 'application/json'})
            request(port, '/api/native/prepare', data=b'', headers={'X-App-Instance': instance})
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                state = request(port, '/api/compute-settings')
                if state['error']:
                    raise RuntimeError(state['error'])
                if not state['preparing'] and state['capabilities'][device]['ready']:
                    break
                time.sleep(1)
            else:
                raise TimeoutError(device + ' preparation failed')
            query = urlencode({'filename': video.name, 'engine': 'whisper-local', 'device': device})
            job = request(port, '/api/upload?' + query, data=video.read_bytes())
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                status = request(port, '/api/speech?job=' + job['id'])
                if status['job']['status'] in {'done', 'error'}:
                    break
                time.sleep(.5)
            assert status['job']['status'] == 'done', status['job'].get('error')
            result = status['result']
            assert result['device'] == device and result['segments']
            assert all(0 <= s['start'] <= s['end'] <= result['duration'] + .01 for s in result['segments'])
            cases.append({'device': device, 'seconds': result['duration'], 'segments': len(result['segments']),
                          'engine': job['device_plan']['engine']})
    finally:
        stop(process, log, port, instance)
        for state_file in (folder / 'windows-app/runtime/backends').glob('*.process.json'):
            state = json.loads(state_file.read_text())
            try:
                worker = psutil.Process(state['pid'])
                assert worker.create_time() == state['created']
                assert Path(worker.exe()).resolve().is_relative_to(folder.resolve())
                worker.terminate()
                worker.wait(timeout=20)
            except psutil.NoSuchProcess:
                pass
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip', type=Path)
    parser.add_argument('--installer', type=Path)
    parser.add_argument('--iscc', type=Path)
    parser.add_argument('--video', type=Path)
    parser.add_argument('--model', type=Path)
    parser.add_argument('--output', type=Path, default=Path('dist/verification-release.json'))
    args = parser.parse_args()
    test_root = Path(tempfile.mkdtemp(prefix='vd-release-'))
    print('Test directory:', test_root, flush=True)
    portable = test_root / 'ZIP тест с пробелом'
    with zipfile.ZipFile(args.zip) as archive:
        manifest = json.loads(archive.read('release-manifest.json'))
        expected = {entry['path'] for entry in manifest['files']} | {'release-manifest.json'}
        assert set(archive.namelist()) == expected, 'ZIP contains missing or unhashed entries'
        archive.extractall(portable)
    print('ZIP extracted; verifying files and offline launch', flush=True)
    with args.zip.open('rb') as source:
        archive_sha = hashlib.file_digest(source, 'sha256').hexdigest()
    report = {'zip_sha256': archive_sha, 'zip_files_verified': manifest_check(portable), 'portable': smoke(portable),
              'clean_vm': False, 'hardware_recognition': False}
    if args.video and args.model:
        print('Testing real CPU/GPU recognition with external weights', flush=True)
        report['hardware_cases'] = hardware_smoke(portable, args.video, args.model)
        report['hardware_recognition'] = True
    if args.installer:
        require_no_registered_install()
        with args.installer.open('rb') as source:
            report['installer_sha256'] = hashlib.file_digest(source, 'sha256').hexdigest()
        print('Testing installer lifecycle', flush=True)
        installed = test_root / 'Installer тест с пробелом'
        install_args = ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/TASKS=', '/NOICONS', '/DIR=' + str(installed)]
        run([args.installer.resolve(), *install_args])
        manifest_check(installed)
        report['installed'] = smoke(installed)
        # Keep user data/config/settings while replacing tracked payload files.
        sentinel = installed / 'windows-app/runtime/workspace/data/keep.txt'
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text('preserve user data', encoding='utf-8')
        settings = installed / 'windows-app/config.local.json'
        saved_settings = settings.read_bytes()
        preserved_setup = {
            'runtime/models/whisper-fixture/model.bin': b'small fixture; no model download',
            'runtime/setup-state.json': b'{"completed":true}',
            'runtime/workspace/.devcontainer/notes-settings.json': b'{"ollama_model":"notes-fixture:9b"}',
            'runtime/workspace/.devcontainer/compute-settings.json': b'{"speech_device":"CPU"}',
        }
        for relative, payload in preserved_setup.items():
            destination = installed / 'windows-app' / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        port = json.loads(saved_settings)['port']
        process, log, instance = start(installed, port)
        try:
            rejected = subprocess.run([str(args.installer.resolve()), *install_args], timeout=300, check=False)
            assert rejected.returncode != 0, 'Installer overwrote a running installation'
            assert request(port, '/health')['instance'] == instance
        finally:
            stop(process, log, port, instance)
        run([args.installer.resolve(), *install_args])
        assert settings.read_bytes() == saved_settings and sentinel.read_text() == 'preserve user data'
        assert all((installed / 'windows-app' / name).read_bytes() == payload for name, payload in preserved_setup.items())
        report['reinstall_preserves_data'] = True
        report['running_upgrade_refused'] = True
        if args.iscc:
            # A distinct installer version, same reviewed code: lifecycle fixture, not a release.
            script = Path(__file__).resolve().parent / 'installer.iss'
            upgrade_payload = test_root / 'upgrade-payload'
            with zipfile.ZipFile(args.zip) as archive:
                archive.extractall(upgrade_payload)
            major, minor, patch = map(int, manifest['version'].split('.'))
            upgrade_version = f'{major}.{minor}.{patch + 1}'
            run([args.iscc.resolve(), '/Qp', '/DPayload=' + str(upgrade_payload), '/DAppVersion=' + upgrade_version, '/O' + str(test_root), script])
            upgrade = test_root / f'VideoDescriptor-{upgrade_version}-windows-x64-setup.exe'
            run([upgrade, *install_args])
            assert sentinel.read_text() == 'preserve user data' and settings.read_bytes() == saved_settings
            assert all((installed / 'windows-app' / name).read_bytes() == payload for name, payload in preserved_setup.items())
            report['upgrade_fixture'] = True
        run([installed / 'unins000.exe', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'])
        assert sentinel.read_text() == 'preserve user data' and settings.read_bytes() == saved_settings
        assert not (installed / 'python/python.exe').exists()
        assert not (installed / 'windows-app/app.py').exists()
        assert all((installed / 'windows-app' / name).read_bytes() == payload for name, payload in preserved_setup.items())
        report['uninstall_preserves_data'] = True
        report['setup_and_model_files_preserved'] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report), flush=True)
    print('Evidence directory:', test_root, flush=True)


if __name__ == '__main__':
    main()
