"""Explicit real WebView2 component acceptance; built-in audio only, no credentials."""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'sandbox'))
from acceptance_ui import CDP, read_http, wait_for


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--reports', type=Path, required=True)
    parser.add_argument('--debug-port', type=int, default=9222)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--with-diarization', action='store_true')
    parser.add_argument('--skip-text-pipeline', action='store_true', help='Run component and diarization acceptance without rechecking translation/notes quality')
    parser.add_argument('--ollama-model', default='qwen3:0.6b')
    parser.add_argument('--diarization-device', choices=['cpu', 'xpu'], default='cpu')
    parser.add_argument('--install-managed', action='store_true', help='Explicitly test managed installation instead of preferring an existing service')
    args = parser.parse_args()
    args.reports.mkdir(parents=True, exist_ok=True)
    report = {'status': 'RUNNING', 'method': 'real installed WebView2 DOM and pointer input',
              'environment': 'Windows Sandbox' if os.environ.get('USERNAME', '').lower() == 'wdagutilityaccount' else 'Windows host',
              'stages': []}
    output = args.reports / 'component-ui.json'
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    cdp = None
    try:
        def target():
            pages = json.loads(read_http(f'http://127.0.0.1:{args.debug_port}/json/list'))
            return next((page for page in pages if page.get('type') == 'page' and page.get('url', '').startswith('http://127.0.0.1:')), None)
        page = wait_for(target)
        cdp = CDP(page['webSocketDebuggerUrl'])
        origin = cdp.evaluate('location.origin')
        def api(path):
            return json.loads(read_http(origin + path))
        health = api('/health')
        if health['installation'] != hashlib.sha256(str(args.root / 'windows-app').encode()).hexdigest():
            raise ValueError('Different installation; refusing product mutations')
        report['version'] = health['version']
        report['component_source_sha256'] = hashlib.sha256((args.root / 'windows-app/component_manager.py').read_bytes()).hexdigest()
        manifest = json.loads((args.root / 'windows-app/component-manifest.json').read_text(encoding='utf-8'))
        if args.cache:
            destination = Path(api('/api/components')['root'])
            downloads = destination / 'downloads'
            downloads.mkdir(exist_ok=True)
            for key in (('ollama', 'managed_python') if args.install_managed else ('managed_python',)):
                item = manifest[key]
                source = args.cache / 'downloads' / item['sha256']
                if source.is_file():
                    with source.open('rb') as stream:
                        if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                            raise ValueError('Acceptance archive cache digest mismatch')
                    shutil.copyfile(source, downloads / item['sha256'])
            model_name = 'community-1-' + manifest['diarization_model']['revision']
            if (args.cache / model_name).is_dir():
                shutil.copytree(args.cache / model_name, destination / model_name, dirs_exist_ok=True)
            if args.install_managed and (args.cache / 'ollama-models').is_dir():
                shutil.copytree(args.cache / 'ollama-models', destination / 'ollama-models', dirs_exist_ok=True)
            report['cache_note'] = 'Reviewed archive/model cache copied; application verifies hashes and performs actual install/inference. No prebuilt environments.'
        cdp.click('#setup-open')
        wait_for(lambda: cdp.evaluate('!document.querySelector("#setup-wizard").hidden'))
        def row(key):
            return next(item for item in api('/api/components')['components'] if item['id'] == key)
        def run_action(name, key, selector, *, consent=None, task=None, timeout=1800):
            before = row(key)
            started = time.monotonic()
            if consent and not cdp.evaluate(f'document.querySelector({json.dumps(consent)}).checked'):
                cdp.click(consent)
            wait_for(lambda: cdp.evaluate(f'!document.querySelector({json.dumps(selector)}).disabled && !document.querySelector("#component-{key} button")?.textContent.includes("Остановить")'))
            cdp.click(selector)
            wait_for(lambda: row(key), lambda item: item.get('operation_id') != before.get('operation_id')
                     or item['state'] in {'downloading', 'installing', 'verifying'}, timeout=30)
            result = wait_for(lambda: api('/api/components'), lambda state: state['active'] is None, timeout=timeout)
            item = next(item for item in result['components'] if item['id'] == key)
            proof = item.get('proof', {})
            ready = item['state'] == 'ready' or (key == 'ollama' and selector in {'#ollama-install', '#ollama-use-connection'}
                                               and item['state'] == 'installed' and proof.get('api_version'))
            evidence = {'name': name, 'status': 'PASS' if ready else 'FAIL', 'state': item['state'], 'proof': proof,
                        'elapsed_seconds': round(time.monotonic() - started, 2), 'message': item['message']}
            report['stages'].append(evidence)
            save()
            if not ready or task and proof.get('task') != task:
                raise RuntimeError(name + ': ' + item['message'])
            wait_for(lambda: cdp.evaluate(f'document.querySelector("#component-{key} .vd-status").textContent.includes({json.dumps(item["message"])}) && !document.querySelector("#component-{key} button").textContent.includes("Остановить")'))
            cdp.screenshot(args.reports / (key + '-' + str(len(report['stages'])) + '.png'))
            return evidence
        run_action('Verify Whisper and prepare installed backend through UI', 'whisper', '#probe-model', timeout=300)
        report['initial_ollama_state'] = row('ollama')['state']
        model_directory = Path(api('/api/components')['root']) / 'ollama-models'
        private_models_before = model_directory.exists()
        if args.install_managed:
            cdp.fill('#ollama-mode', 'managed')
            run_action('Install official Ollama through AI Settings', 'ollama', '#ollama-install', consent='#ollama-install-consent')
        else:
            cdp.fill('#ollama-mode', 'existing')
            run_action('Use existing Ollama without second server or downloads', 'ollama', '#ollama-use-connection')
            report['external_reuse'] = {'private_model_directory_existed_before': private_models_before, 'private_model_directory_exists_after': model_directory.exists(), 'ownership': api('/api/components')['ollama_connection']['ownership']}
            if not private_models_before and model_directory.exists():
                raise AssertionError('External connection unexpectedly created a private model directory')
        wait_for(lambda: cdp.evaluate('document.querySelector("#ollama-catalog").options.length > 0'))
        if args.ollama_model in {item['name'] for item in manifest['ollama_models']}:
            cdp.fill('#ollama-catalog', args.ollama_model)
        cdp.fill('#ollama-task', 'translation')
        available = json.loads(read_http(origin + '/api/setup/ollama'))['models']
        if not any(item['name'] == args.ollama_model for item in available):
            if not args.install_managed:
                raise RuntimeError('Existing service has no selected test model; refusing an unnecessary automatic download')
            run_action('Pull small model and verify real generation through UI', 'ollama', '#ollama-pull',
                       consent='#ollama-pull-consent', task='translation', timeout=1200)
        cdp.click('#ollama-refresh')
        wait_for(lambda: cdp.evaluate(f'[...document.querySelector("#ollama-model").options].some(o=>o.value==={json.dumps(args.ollama_model)})'))
        cdp.fill('#ollama-model', args.ollama_model)
        cdp.fill('#ollama-task', 'translation')
        run_action('Select and test existing translation model through UI', 'ollama', '#ollama-connect', task='translation', timeout=300)
        cdp.fill('#ollama-task', 'notes')
        run_action('Select and test notes model through UI', 'ollama', '#ollama-connect', task='notes', timeout=300)
        if args.with_diarization:
            cdp.fill('#diarization-device', args.diarization_device)
            run_action('Install isolated CPython and pyannote ' + args.diarization_device.upper() + ' through UI', 'diarization', '#diarization-install',
                       consent='#diarization-consent', timeout=2400)
        cdp.click('#setup-finish')
        wait_for(lambda: cdp.evaluate('location.hash === "#records"'))
        cdp.click('#new-record-open')
        wait_for(lambda: cdp.evaluate('!document.querySelector("#new-record-view").hidden'))
        document = cdp.call('DOM.getDocument')['root']['nodeId']
        node = cdp.call('DOM.querySelector', nodeId=document, selector='#file')['nodeId']
        cdp.call('DOM.setFileInputFiles', nodeId=node, files=[str(args.root / 'windows-app/samples/speech-check.mp4')])
        cdp.fill('#language', 'en')
        wait_for(lambda: not cdp.evaluate('document.querySelector("#start").disabled'))
        cdp.click('#start')
        def completed():
            text = cdp.visible_text('#status')
            if text == 'Нужна проверка':
                raise RuntimeError(cdp.visible_text('#progress-text'))
            return text == 'Готово'
        wait_for(completed, timeout=240)
        source_job = cdp.evaluate('new URLSearchParams(location.search).get("job")')
        for stage, button in ([] if args.skip_text_pipeline else [('translation', '#translate-run'), ('notes', '#notes-run')]) + ([('diarization', '#diarize-run')] if args.with_diarization else []):
            cdp.call('Page.navigate', url=origin + '/?job=' + source_job + '#records')
            wait_for(lambda: cdp.evaluate('!!document.querySelector("#setup-open")'))
            wait_for(completed)
            started = time.monotonic()
            wait_for(lambda button=button: not cdp.evaluate(f'document.querySelector({json.dumps(button)}).disabled'))
            cdp.click(button)
            wait_for(lambda: cdp.evaluate('new URLSearchParams(location.search).get("job")'), lambda job: job and job != source_job)
            wait_for(completed, timeout=900)
            job = cdp.evaluate('new URLSearchParams(location.search).get("job")')
            result = api('/api/speech?job=' + job)
            if result['job']['status'] != 'done':
                raise RuntimeError('Pipeline failed: ' + stage)
            report['stages'].append({'name': 'Real UI pipeline: ' + stage, 'status': 'PASS',
                                     'elapsed_seconds': round(time.monotonic() - started, 2),
                                     'segments': len(result['result']['segments'])})
            save()
            cdp.screenshot(args.reports / (stage + '.png'))
        report['status'] = 'PASS'
    except Exception as exc:  # noqa: BLE001 — acceptance boundary; only built-in sample and no token input.
        report.update(status='FAIL', error=f'{type(exc).__name__}: {exc}')
        if cdp:
            cdp.screenshot(args.reports / 'failure.png')
    finally:
        save()
        if cdp:
            cdp.sock.close()
    print(json.dumps({'status': report['status'], 'report': str(output)}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
