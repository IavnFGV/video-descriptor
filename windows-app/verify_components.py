"""Explicit installed component E2E. Never runs from Fast CI; no user media."""
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hf-token-file', type=Path)
    parser.add_argument('--reuse-directory', type=Path, help="Reuse only this runner marked isolated user-data directory")
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('Windows only')
    directory = args.reuse_directory.resolve() if args.reuse_directory else Path(tempfile.mkdtemp(prefix='AI компоненты ', dir=args.output.resolve().parent))
    marker = directory / '.component-acceptance.json'
    if args.reuse_directory and not marker.is_file():
        raise ValueError('Refusing an unmarked directory')
    marker.write_text('{"test_installation": true}', encoding='utf-8')
    root = directory / 'Video Descriptor'
    report = {'status': 'RUNNING', 'method': 'installed Windows application HTTP API; no UI claim',
              'environment': 'Windows host; isolated PATH and user data; not a clean VM', 'root': str(root), 'stages': []}
    with args.installer.open('rb') as stream:
        report['installer_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    subprocess.run([str(args.installer.resolve()), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                    '/DIR=' + str(root), '/TASKS='], check=True, timeout=180)
    config = {'port': 18980, 'workspace': 'runtime/workspace', 'speech_device': 'CPU',
              'npu_worker_directory': str(root / 'no-benchmark'), 'whisper_model_directory': str(root / 'no-model'),
              'cpu_url': 'http://127.0.0.1:18967', 'gpu_url': 'http://127.0.0.1:18968',
              'npu_url': 'http://127.0.0.1:18966', 'ollama_url': 'http://127.0.0.1:18934'}
    local = root / 'windows-app/config.local.json'
    if not args.reuse_directory:
        local.write_text(json.dumps(config), encoding='utf-8')
    # No system Python/PATH, no inherited Hugging Face credentials or model cache.
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'HF_', 'OLLAMA', 'PIP_'))}
    env.update(PATH=str(Path(os.environ['SystemRoot']) / 'System32'), LOCALAPPDATA=str(directory / 'Личные данные'),
               PYTHONUTF8='1', HF_HUB_DISABLE_TELEMETRY='1')
    log = (directory / 'application.log').open('wb')
    app = subprocess.Popen([str(root / 'python/python.exe'), '-X', 'utf8', str(root / 'windows-app/app.py'), '--no-browser'],
                           env=env, stdout=log, stderr=log, creationflags=0x08000000)
    session = requests.Session()
    session.trust_env = False
    instance = None
    def api(path, body=None):
        response = session.get('http://127.0.0.1:18980' + path, timeout=30) if body is None else session.post(
            'http://127.0.0.1:18980' + path, json=body, headers={'X-App-Instance': instance}, timeout=30)
        response.raise_for_status()
        return response.json()
    try:
        for _ in range(100):
            try:
                instance = api('/health')['instance']
                break
            except requests.RequestException:
                time.sleep(.5)
        if not instance:
            raise RuntimeError('Installed app did not start')
        report['version'] = api('/health')['version']
        api('/api/compute-settings', {'speech_device': 'CPU'})
        def stage(name, key, action, **body):
            started = time.monotonic()
            evidence = {'name': name, 'status': 'RUNNING'}
            report['stages'].append(evidence)
            save()
            api('/api/components', {'component': key, 'action': action, 'confirmed': True, **body})
            for _ in range(3600):
                status = api('/api/components')
                row = next(item for item in status['components'] if item['id'] == key)
                evidence.update(state=row['state'], message=row['message'])
                save()
                if not status['active']:
                    passed = row['state'] == 'ready' or (key == 'ollama' and action == 'install' and row['state'] == 'installed' and row.get('proof', {}).get('api_version'))
                    evidence.update(status='PASS' if passed else 'FAIL', proof=row.get('proof'),
                                    elapsed_seconds=round(time.monotonic() - started, 2),
                                    version=row.get('version'), device=row.get('device'), fallback_reason=row.get('fallback_reason'))
                    save()
                    if evidence['status'] != 'PASS':
                        raise RuntimeError(name + ': ' + row['message'])
                    return
                time.sleep(1)
            raise RuntimeError(name + ': timeout')
        stage('Whisper automatic download and real CPU inference', 'whisper', 'install')
        stage('Ollama official standalone installation and API', 'ollama', 'install')
        stage('Ollama small model download and real generation', 'ollama', 'pull', model='qwen3:0.6b', task='translation')
        stage('Ollama notes model generation check', 'ollama', 'check', model='qwen3:0.6b', task='notes')
        sample = root / 'windows-app/samples/speech-check.mp4'
        uploaded = session.post('http://127.0.0.1:18980/api/upload?filename=speech-check.mp4&engine=whisper-local&device=CPU&language=en&speech_only=true',
                                data=sample.read_bytes(), headers={'X-App-Instance': instance}, timeout=30)
        uploaded.raise_for_status()
        def finished(job):
            for _ in range(900):
                value = api('/api/speech?job=' + job['id'])
                if value['job']['status'] in {'done', 'error'}:
                    if value['job']['status'] != 'done':
                        raise RuntimeError(value['job'].get('error', 'Pipeline failed'))
                    return value
                time.sleep(1)
            raise RuntimeError('Pipeline timeout')
        speech = finished(uploaded.json())
        for task in ('translate', 'notes'):
            began = time.monotonic()
            result = finished(api('/api/native/postprocess', {'folder': speech['job']['folder'], 'task': task}))
            report['stages'].append({'name': 'Real installed pipeline: ' + task, 'status': 'PASS',
                                     'elapsed_seconds': round(time.monotonic() - began, 2),
                                     'segments': len(result['result']['segments']),
                                     'has_translation': result['result'].get('has_translation', False)})
            save()
        token = None
        if args.hf_token_file and args.hf_token_file.is_file():
            for line in args.hf_token_file.read_text(encoding='utf-8-sig').splitlines():
                if '=' in line and not line.startswith('#'):
                    value = line.split('=', 1)[1].strip().strip('\"\'')
                    if value.startswith('hf_'):
                        token = value
        if token:
            stage('Managed CPython, pyannote CPU installation and real inference', 'diarization', 'install', device='cpu', token=token)
            stage('Managed pyannote XPU installation and real inference', 'diarization', 'install', device='xpu')
        else:
            report['stages'].append({'name': 'pyannote CPU/XPU', 'status': 'BLOCKED', 'reason': 'No authorized HF token supplied'})
        report['status'] = 'PASS' if all(row['status'] == 'PASS' for row in report['stages']) else 'BLOCKED'
    except Exception as exc:  # noqa: BLE001 — persisted acceptance result, no credential values.
        report.update(status='FAIL', error=str(exc))
    finally:
        save()
        if instance:
            try:
                api('/api/native/stop', {})
            except requests.RequestException:
                pass
        if app.poll() is None:
            app.terminate()
            app.wait(timeout=20)
        log.close()
        # Keep installation/data for diagnosis, not a claim of clean uninstall.
    print(json.dumps({'status': report['status'], 'report': str(args.output)}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
