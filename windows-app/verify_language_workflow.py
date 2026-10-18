"""Opt-in real packaged CPU ASR, Ollama notes and translation; never downloads models."""
import argparse
import hashlib
import json
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlencode

import psutil
from verify_release import configure, free_port, manifest_check, request, start, stop


def wait_for(read, done, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = read()
        if done(value):
            return value
        time.sleep(1)
    raise TimeoutError('Workflow stage did not complete')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip', type=Path)
    parser.add_argument('--video', required=True, type=Path)
    parser.add_argument('--model', required=True, type=Path)
    parser.add_argument('--ollama-model', default='qwen3.5:9b')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix='vd-language-')) / 'Полный путь с пробелом'
    root.mkdir()
    print('Evidence directory:', root, flush=True)
    with zipfile.ZipFile(args.zip) as archive:
        archive.extractall(root)
    count = manifest_check(root)
    port = free_port()
    local = configure(root, port)
    settings = json.loads(local.read_text())
    settings['ollama_url'] = 'http://127.0.0.1:11434'
    local.write_text(json.dumps(settings), encoding='utf-8')
    process, log, instance = start(root, port)
    began = time.monotonic()
    with args.zip.open('rb') as source:
        archive_sha = hashlib.file_digest(source, 'sha256').hexdigest()
    version = json.loads((root / 'release-manifest.json').read_text())['version']
    report = {'version': version, 'environment': 'real Windows host / extracted ZIP',
              'clean_vm': False, 'models_downloaded': False, 'zip_files_verified': count,
              'zip_sha256': archive_sha}

    def post(path, body):
        return request(port, path, data=json.dumps(body).encode(),
                       headers={'Content-Type': 'application/json', 'X-App-Instance': instance})

    try:
        post('/api/setup/model', {'path': str(args.model.resolve())})
        post('/api/setup/ollama', {'model': args.ollama_model})
        post('/api/compute-settings', {'speech_device': 'CPU'})
        post('/api/native/prepare', {})
        caps = wait_for(lambda: request(port, '/api/compute-settings'),
                        lambda s: not s['preparing'], 240)
        assert caps['capabilities']['CPU']['ready'], caps['error']
        print('Packaged CPU ready; processing video', flush=True)
        job = request(port, '/api/upload?' + urlencode({'filename': args.video.name,
                      'engine': 'whisper-local', 'device': 'CPU'}), data=args.video.read_bytes())
        speech = wait_for(lambda: request(port, '/api/speech?job=' + job['id']),
                          lambda s: s['job']['status'] in {'done', 'error'}, 240)
        assert speech['job']['status'] == 'done', speech['job'].get('error')
        assert speech['result']['segments'] and speech['result']['device'] == 'CPU'
        report['asr'] = {'device': 'CPU', 'seconds': speech['result']['duration'],
                         'segments': len(speech['result']['segments'])}
        print('ASR passed; generating notes with installed Ollama', flush=True)
        job = post('/api/native/postprocess', {'folder': speech['job']['folder'], 'task': 'notes'})
        assert job['translation_model'] == args.ollama_model
        notes = wait_for(lambda: next(item for item in request(port, '/api/jobs') if item['id'] == job['id']),
                         lambda s: s['status'] in {'done', 'error'}, 300)
        assert notes['status'] == 'done', notes.get('error')
        workspace = root / 'windows-app/runtime/workspace'
        folder = workspace / 'output' / job['folder']
        print('Queued notes and translation passed with packaged Python', flush=True)
        transcript = json.loads((folder / 'transcript.json').read_text(encoding='utf-8'))
        translations = json.loads((folder / 'translations.json').read_text(encoding='utf-8'))
        assert all(translations.get(row['id'], '').strip() for row in transcript)
        assert not json.loads((folder / 'translation-errors.json').read_text())
        generated = json.loads((folder / 'notes.json').read_text(encoding='utf-8'))
        chapters = json.loads((folder / 'chapters.json').read_text(encoding='utf-8'))
        assert generated['notes'] and chapters and (folder / 'report.html').is_file()
        query = urlencode({'folder': job['folder'], 'language': 'ru', 'format': 'srt'})
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/subtitles?{query}', timeout=10) as response:
            assert '-->' in response.read().decode('utf-8')
        report.update(status='passed', postprocess_api=True, model_pinned_to_job=True,
                      model=args.ollama_model, translated_segments=len(transcript),
                      notes=len(generated['notes']), chapters=len(chapters), translated_srt=True,
                      elapsed_seconds=round(time.monotonic() - began, 2))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report), flush=True)
    finally:
        try:
            try:
                stop(process, log, port, instance)
            except urllib.error.HTTPError:
                # Failed test can leave its own queue active; preserve the original failure.
                process.terminate()
                process.wait(timeout=20)
        finally:
            # Only this disposable copy's Python processes; external Ollama is preserved.
            executable = (root / 'python/python.exe').resolve()
            for child in psutil.process_iter(['exe']):
                try:
                    if child.info['exe'] and Path(child.info['exe']).resolve() == executable:
                        child.terminate()
                        child.wait(timeout=20)
                except psutil.NoSuchProcess:
                    pass


if __name__ == '__main__':
    main()
