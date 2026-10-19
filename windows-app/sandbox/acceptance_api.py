"""Real installed-app HTTP acceptance, usable in a guest and on a CI runner.

This is deliberately an API test. It makes no claim of clicking desktop controls.
Only synthetic bundled speech is submitted; no host/private media is discovered.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlencode, urlsplit


def wait_for(read, done=bool, timeout=240):
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            value = read()
            if done(value):
                return value
        except (OSError, ValueError) as exc:
            error = str(exc)
        time.sleep(0.5)
    raise TimeoutError(f'Acceptance deadline ({timeout}s), last error: {error}')


def validate_speech(result):
    rows = result.get('segments', [])
    if result.get('device') != 'CPU' or not rows:
        raise ValueError('Real CPU speech result with nonempty segments is required')
    if not all(row.get('text', '').strip() and 0 <= row['start'] <= row['end'] <= result['duration'] + 0.1 for row in rows):
        raise ValueError('Speech contains empty text or invalid timestamps')
    return {'device': 'CPU', 'segments': len(rows), 'duration': result['duration'],
            'text': ' '.join(row['text'] for row in rows), 'timestamps_valid': True}


def preparation_complete(state):
    # A snapshot can finish collecting capabilities just before the background
    # preparation flips its flag. Require positive readiness or a concrete error.
    return not state['preparing'] and (state['capabilities']['CPU']['ready'] or bool(state.get('error')))


def validate_saved(folder, *, notes=False):
    transcript = json.loads((folder / 'transcript.json').read_text(encoding='utf-8'))
    translated = json.loads((folder / 'translations.json').read_text(encoding='utf-8'))
    if not transcript or not all(translated.get(row['id'], '').strip() for row in transcript):
        raise ValueError('Saved translation does not cover every transcript segment')
    errors = folder / 'translation-errors.json'
    if errors.exists() and json.loads(errors.read_text(encoding='utf-8')):
        raise ValueError('Saved translation has errors')
    if not any('\u0400' <= char <= '\u04ff' for char in ' '.join(translated.values())):
        raise ValueError('Requested Russian translation has no Cyrillic text')
    result = {'translated_segments': len(transcript), 'translations': translated}
    if notes:
        saved = json.loads((folder / 'notes.json').read_text(encoding='utf-8'))
        chapters = json.loads((folder / 'chapters.json').read_text(encoding='utf-8'))
        if not saved.get('notes') or not chapters or not (folder / 'report.html').is_file():
            raise ValueError('Saved notes, chapters or HTML report are missing')
        result.update(notes=len(saved['notes']), chapters=len(chapters))
    return result


class InstalledAPI:
    def __init__(self, root, reports, *, model_directory=None, ollama_model='qwen3.5:9b', plan=None):
        self.root = root.resolve()
        self.reports = reports.resolve()
        self.reports.mkdir(parents=True, exist_ok=True)
        self.model_directory = model_directory
        self.ollama_model = ollama_model
        self.plan = plan or {}
        settings = json.loads((self.root / 'windows-app/config.example.json').read_text(encoding='utf-8'))
        local = self.root / 'windows-app/config.local.json'
        if local.is_file():
            settings.update(json.loads(local.read_text(encoding='utf-8')))
        self.settings = settings
        self.origin = 'http://127.0.0.1:' + str(settings['port'])
        self.instance = None

    def request(self, path, *, body=None, raw=None, base=None):
        base = base or self.origin
        if urlsplit(base).hostname not in {'127.0.0.1', 'localhost', '::1'}:
            raise ValueError('Acceptance only connects to explicit loopback services')
        headers = {}
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        if self.instance:
            headers['X-App-Instance'] = self.instance
        req = urllib.request.Request(base + path, data=data, headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=300 if base != self.origin else 45) as response:
            value = response.read()
            return json.loads(value) if 'json' in response.headers.get('Content-Type', '') else value

    def connect(self):
        health = wait_for(lambda: self.request('/health'), timeout=90)
        expected = hashlib.sha256(str(self.root / 'windows-app').encode()).hexdigest()
        if health.get('app') != 'video-descriptor-windows' or health.get('installation') != expected:
            raise ValueError('Loopback port belongs to another installation')
        self.instance = health['instance']
        return {key: value for key, value in health.items() if key != 'instance'}

    def job_done(self, job):
        result = wait_for(lambda: self.request('/api/speech?job=' + job['id']),
                          lambda value: value['job']['status'] in {'done', 'error'}, timeout=600)
        if result['job']['status'] != 'done':
            raise RuntimeError(result['job'].get('error', 'Job failed'))
        return result

    def run(self, stage):
        report = {'stage': stage, 'status': 'FAIL', 'method': 'real installed application HTTP API; no UI claim'}
        started = time.monotonic()
        try:
            report['installation'] = self.connect()
            if stage == 'desktop':
                report['diagnostics'] = self.request('/api/setup/diagnostics')
                report['setup'] = self.request('/api/setup')
            elif stage == 'whisper':
                if self.plan.get('network_download'):
                    self.request('/api/setup/download', body={'confirmed': True})
                    operation = wait_for(lambda: self.request('/api/setup')['operation'],
                                         lambda op: op.get('kind') == 'download' and op['status'] in {'done', 'error'}, timeout=900)
                    if operation['status'] != 'done':
                        raise RuntimeError(operation.get('message', 'Model download failed'))
                else:
                    model = self.model_directory
                    if model is None:
                        objects = [obj for obj in self.plan.get('cache', []) if obj['component'] == 'whisper-model']
                        if not objects:
                            raise ValueError('No verified test model provided')
                        model = Path('C:/VD-Cache') / objects[0]['id'] / objects[0].get('payload', '')
                    report['model'] = self.request('/api/setup/model', body={'path': str(model.resolve())})
                self.request('/api/compute-settings', body={'speech_device': 'CPU'})
                self.request('/api/native/prepare', body={})
                compute = wait_for(lambda: self.request('/api/compute-settings'), preparation_complete)
                report['compute'] = compute
                if not compute['capabilities']['CPU']['ready']:
                    raise RuntimeError(compute.get('error') or compute['capabilities']['CPU']['reason'])
                report['worker_health'] = self.request('/health', base=self.settings['cpu_url'])
                sample = self.root / 'windows-app/samples/speech-check.mp4'
                job = self.request('/api/upload?' + urlencode({'filename': sample.name, 'engine': 'whisper-local',
                                    'device': 'CPU', 'language': 'en', 'speech_only': 'true'}), raw=sample.read_bytes())
                result = self.job_done(job)
                report['asr'] = validate_speech(result['result'])
                report['result'] = result
                (self.reports / 'workflow-state.json').write_text(json.dumps({'source_job': job['id']}), encoding='utf-8')
            elif stage == 'ollama-install':
                report['ollama_version'] = wait_for(lambda: self.request('/api/version', base=self.settings['ollama_url']))
                report['app_status'] = self.request('/api/setup/ollama')
            elif stage == 'ollama-model':
                self.request('/api/setup/ollama', body={'model': self.ollama_model, 'task': 'translation'})
                tags = self.request('/api/tags', base=self.settings['ollama_url'])
                found = [model for model in tags['models'] if model['name'] == self.ollama_model and model.get('digest')]
                if not found:
                    raise ValueError('Installed Ollama model/digest absent')
                report['installed_model'] = found[0]
            elif stage == 'ollama-inference':
                result = self.request('/api/generate', base=self.settings['ollama_url'], body={
                    'model': self.ollama_model, 'prompt': 'Reply with one short sentence about a train.',
                    'think': False, 'stream': False, 'options': {'temperature': 0, 'num_predict': 128}})
                if not result.get('done') or not result.get('response', '').strip():
                    raise ValueError('Real generation returned no completed text')
                report['response'] = result
            elif stage in {'translation', 'notes'}:
                state = json.loads((self.reports / 'workflow-state.json').read_text(encoding='utf-8'))
                source = self.request('/api/speech?job=' + state['source_job'])
                self.request('/api/setup/ollama', body={'model': self.ollama_model,
                                                       'task': 'notes' if stage == 'notes' else 'translation'})
                job = self.request('/api/native/postprocess', body={'folder': source['job']['folder'],
                                    'task': 'notes' if stage == 'notes' else 'translate'})
                result = self.job_done(job)
                folder = (self.root / 'windows-app/runtime/workspace/output' / result['job']['folder']).resolve()
                if not folder.is_relative_to((self.root / 'windows-app/runtime/workspace/output').resolve()):
                    raise ValueError('Result escaped isolated test workspace')
                report['saved'] = validate_saved(folder, notes=stage == 'notes')
                subtitle = self.request('/api/subtitles?' + urlencode({'folder': result['job']['folder'], 'language': 'ru', 'format': 'srt'}))
                if '-->' not in subtitle.decode('utf-8'):
                    raise ValueError('API export returned no subtitle timestamps')
                (self.reports / 'translated.srt').write_bytes(subtitle)
                if stage == 'notes':
                    (self.reports / 'notes-report.html').write_bytes((folder / 'report.html').read_bytes())
                report['job'] = result['job']
            else:
                raise ValueError('Unknown acceptance stage: ' + stage)
            report['status'] = 'PASS'
        except Exception as exc:  # noqa: BLE001 -- persist test failures before returning to orchestrator
            report['error'] = f'{type(exc).__name__}: {exc}'
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        (self.reports / (stage + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--reports', type=Path, required=True)
    parser.add_argument('--model', default='qwen3.5:9b')
    parser.add_argument('--plan', type=Path, default=Path('C:/VD-Acceptance/plan.json'))
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding='utf-8-sig')) if args.plan.exists() else {}
    driver = InstalledAPI(args.root, args.reports, ollama_model=args.model, plan=plan)
    result = driver.run(args.stage)
    print(json.dumps({'stage': args.stage, 'status': result['status']}))


if __name__ == '__main__':
    main()
