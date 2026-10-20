"""Install an EXE into a fresh test directory and verify real CPU ASR via its API.

Runs the test with the installed Python. Never mocks the worker or uses host NPU.
Optional --with-ollama verifies an explicitly supplied loopback Ollama/model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'sandbox'))


def verify_payload(root, archive):
    with zipfile.ZipFile(archive) as package:
        expected = json.loads(package.read('release-manifest.json'))
    installed = json.loads((root / 'release-manifest.json').read_text(encoding='utf-8'))
    if installed != expected:
        raise ValueError('Installed release manifest does not match the tested ZIP')
    critical = {'windows-app/component_manager.py', 'windows-app/component-manifest.json',
                'windows-app/requirements-pyannote-cpu.lock', 'windows-app/requirements-pyannote-xpu.lock',
                'windows-app/diarization_worker.py', 'windows-app/app.py', 'windows-app/compute.py', 'windows-app/setup_service.py',
                'windows-app/whisper_worker.py', 'windows-app/desktop-sdk/VideoDescriptor.exe'}
    entries = {item['path']: item for item in expected['files']}
    for name in critical:
        path = root / name
        if name not in entries or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entries[name]['sha256']:
            raise ValueError('Installed critical payload mismatch: ' + name)
    with archive.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    return {'version': installed['version'], 'critical_files_verified': len(critical), 'zip_sha256': digest}


def check_installed(args):
    import psutil
    from acceptance_api import InstalledAPI, wait_for
    from verify_release import configure, free_port, start, stop

    root = args.installed_root.resolve()
    expected_python = root / 'python/python.exe'
    if not expected_python.samefile(sys.executable):
        raise ValueError('Verification must run with this installation\'s embedded Python')
    report = {'status': 'FAIL', 'method': 'real installed application API and WebView2 UI' if args.ui else 'real installed application API; no UI claim',
              'environment': 'Windows Sandbox' if os.environ.get('USERNAME', '').lower() == 'wdagutilityaccount'
              else 'GitHub Actions Windows' if os.environ.get('GITHUB_ACTIONS') == 'true' else 'isolated Windows test',
              'installed_root': str(root), 'embedded_python': sys.version, 'models_downloaded': False,
              'stages': [], 'started_at': time.time(), 'git_sha': os.environ.get('GITHUB_SHA')}
    process = log = None
    instance = None
    started = time.monotonic()
    try:
        if not (root / '.acceptance-installation.json').is_file():
            raise ValueError('Only a marked, fresh test installation can be reconfigured')
        report.update(verify_payload(root, args.zip))
        plan_path = Path('C:/VD-Acceptance/plan.json')
        if plan_path.is_file():
            report['git_sha'] = json.loads(plan_path.read_text(encoding='utf-8-sig')).get('git_sha')
        port = free_port()
        local = configure(root, port)
        settings = json.loads(local.read_text(encoding='utf-8'))
        # Keep the initial unavailable fixture endpoint: acceptance must exercise
        # changing the selected endpoint after startup, not only initial configuration.
        local.write_text(json.dumps(settings), encoding='utf-8')
        process, log, instance = start(root, port)
        driver = InstalledAPI(root, args.output.parent, model_directory=args.model,
                              ollama_model=args.ollama_model)
        if args.with_ollama:
            driver.connect()
            driver.request('/api/components', body={'component': 'ollama', 'action': 'connect',
                           'mode': 'existing' if args.ollama_url == 'http://127.0.0.1:11434' else 'service',
                           'url': args.ollama_url})
            def selected_connection():
                state = driver.request('/api/components')
                row = next(item for item in state['components'] if item['id'] == 'ollama')
                if not state['active'] and row['state'] == 'error':
                    raise ValueError(row['message'])
                return state
            connected = wait_for(selected_connection, lambda state: not state['active'] and state['ollama_connection']['url'] == args.ollama_url)
            report['endpoint_transition'] = {'before': settings['ollama_url'], 'after': args.ollama_url,
                                             'mode': connected['ollama_connection']['mode'], 'method': 'explicit connection change after installed application startup'}
            driver.settings['ollama_url'] = args.ollama_url
        stages = ['desktop', 'whisper']
        if args.with_ollama:
            stages += ['ollama-install', 'ollama-model', 'ollama-inference', 'translation', 'notes']
        for stage in stages:
            result = driver.run(stage)
            report['stages'].append(result)
            if result['status'] != 'PASS':
                raise RuntimeError(result.get('error', stage + ' failed'))
        if args.ui:
            from verify_workspace_ui import installed_workflow

            ui_output = args.output.parent / 'webview2-ui'
            report['ui'] = installed_workflow(root, port, ui_output, with_ollama=args.with_ollama)
        if args.component_devices:
            from verify_workspace_ui import installed_component_workflow
            report['component_ui'] = []
            for device in args.component_devices:
                report['component_ui'].append(installed_component_workflow(root, port, args.output.parent / ('component-ui-' + device),
                                               args.ollama_model, args.component_cache, device))
        report['status'] = 'PASS'
    except Exception as exc:  # noqa: BLE001 -- acceptance runner persists every failure
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        try:
            if process is not None:
                try:
                    stop(process, log, port, instance)
                except (OSError, ValueError, AssertionError, subprocess.TimeoutExpired):
                    process.terminate()
                    process.wait(timeout=20)
                for child in psutil.process_iter(['exe']):
                    try:
                        executable = Path(child.info['exe']).resolve() if child.info['exe'] else None
                        owned = executable == expected_python or (args.ui and executable and executable.is_relative_to(root))
                        if child.pid != os.getpid() and owned:
                            child.terminate()
                            child.wait(timeout=20)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
        except (OSError, ValueError, psutil.Error, subprocess.SubprocessError) as exc:
            report.update(status='FAIL', cleanup_error=str(exc))
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['status'] == 'PASS' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--installer', type=Path)
    group.add_argument('--installed-root', type=Path)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--with-ollama', action='store_true')
    parser.add_argument('--component-cache', type=Path, help='Verified task-owned CPython/model cache for explicit component UI acceptance')
    parser.add_argument('--component-devices', nargs='+', choices=['cpu', 'xpu'], default=[])
    parser.add_argument('--ui', action='store_true', help='Run real installed WebView2 input/editor/export acceptance')
    parser.add_argument('--ollama-url', default='http://127.0.0.1:11434')
    parser.add_argument('--ollama-model', default='qwen3.5:9b')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Windows installer verification requires Windows')
    if args.installed_root:
        return check_installed(args)
    from verify_release import require_no_registered_install
    require_no_registered_install()
    root = Path(tempfile.mkdtemp(prefix='vd-installed-acceptance-')) / 'Installed preview'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    command = [str(args.installer.resolve()), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
               '/SP-', '/TASKS=', '/NOICONS', '/DIR=' + str(root),
               '/LOG=' + str(args.output.parent.resolve() / 'acceptance-installer.log')]
    result_code = 1
    try:
        subprocess.run(command, check=True, timeout=600)
        (root / '.acceptance-installation.json').write_text(json.dumps({'purpose': 'disposable installed API acceptance'}), encoding='utf-8')
        child = [str(root / 'python/python.exe'), '-X', 'utf8', str(Path(__file__).resolve()),
                 '--installed-root', str(root), '--zip', str(args.zip.resolve()), '--model', str(args.model.resolve()),
                 '--output', str(args.output.resolve()), '--ollama-url', args.ollama_url,
                 '--ollama-model', args.ollama_model]
        if args.with_ollama:
            child.append('--with-ollama')
        if args.component_cache:
            child += ['--component-cache', str(args.component_cache.resolve())]
        if args.component_devices:
            child += ['--component-devices', *args.component_devices]
        if args.ui:
            child.append('--ui')
        result_code = subprocess.run(child, check=False, timeout=3600 if args.component_devices else 1800).returncode
        if not args.output.is_file():
            args.output.write_text(json.dumps({'status': 'FAIL', 'error': 'Embedded verifier exited without a result',
                                               'exit_code': result_code, 'installed_root': str(root)}), encoding='utf-8')
            result_code = 1
    except (OSError, subprocess.SubprocessError) as exc:
        args.output.write_text(json.dumps({'status': 'FAIL', 'error': str(exc), 'installed_root': str(root)}), encoding='utf-8')
    finally:
        uninstaller = root / 'unins000.exe'
        if uninstaller.is_file():
            cleanup_error = None
            try:
                cleaned = subprocess.run([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'],
                                         check=False, timeout=180)
                if cleaned.returncode:
                    cleanup_error = 'Isolated test uninstaller exit ' + str(cleaned.returncode)
            except (OSError, subprocess.SubprocessError) as exc:
                cleanup_error = str(exc)
            if cleanup_error:
                result_code = 1
                report = json.loads(args.output.read_text(encoding='utf-8')) if args.output.exists() else {}
                report.update(status='FAIL', cleanup_error=cleanup_error)
                args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return result_code


if __name__ == '__main__':
    raise SystemExit(main())
