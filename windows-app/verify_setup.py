"""Explicit isolated first-run -> CPU ASR -> export check using existing model/audio."""
import argparse
import io
import json
import shutil
import socket
import tempfile
import threading
import time
import wave
from pathlib import Path

import app
import build_release
import psutil
import requests
from compute import ComputeManager

from video_descriptor.jobs import read_json


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def until(work, predicate, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = work()
        if predicate(result):
            return result
        time.sleep(.2)
    raise RuntimeError('Setup verification timed out')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--audio', type=Path, required=True)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix='setup-check-', dir=app.HERE / 'runtime'))
    for source in build_release.source_paths():
        target = root / source.relative_to(app.REPOSITORY)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    app.HERE = root / 'windows-app'
    value = json.loads((app.HERE / 'config.example.json').read_text())
    value.update(workspace=str(app.HERE / 'runtime/workspace'), npu_worker_directory=str(root / 'no-external-worker'),
                 openvino_python=str(args.python.resolve()), whisper_model_directory=str(root / 'missing-model'),
                 cpu_url='http://127.0.0.1:' + str(free_port()), npu_url='http://127.0.0.1:' + str(free_port()),
                 gpu_url='http://127.0.0.1:' + str(free_port()))
    workspace = Path(value['workspace'])
    workspace.mkdir(parents=True)
    app.environment(value)
    with wave.open(str(args.audio), 'rb') as source:
        data = io.BytesIO()
        with wave.open(data, 'wb') as target:
            target.setparams(source.getparams())
            target.writeframes(source.readframes(160000))
        audio = data.getvalue()
    session = requests.Session()
    session.trust_env = False
    report = {'device': 'CPU', 'cloud_requests': False, 'model_downloaded': False}
    with app.NativeHTTPServer(('127.0.0.1', 0), app.make_handler(value, 'verification')) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)

        def get(path):
            response = session.get(base + path, timeout=30)
            response.raise_for_status()
            return response.json()

        def post(path, body):
            response = session.post(base + path, json=body, headers={'X-App-Instance': 'verification'}, timeout=30)
            response.raise_for_status()
            return response.json()
        try:
            assert not get('/api/setup')['model_present']
            post('/api/setup/model', {'path': str(args.model.resolve())})
            post('/api/compute-settings', {'speech_device': 'CPU'})
            post('/api/native/prepare', {})
            compute = until(lambda: get('/api/compute-settings'), lambda c: not c['preparing'])
            assert compute['capabilities']['CPU']['ready'], compute
            response = session.post(base + '/api/setup/probe', data=audio,
                                    headers={'X-App-Instance': 'verification'}, timeout=30)
            response.raise_for_status()
            probe = until(lambda: get('/api/setup')['operation'], lambda s: s['status'] in {'done', 'error'})
            assert probe['status'] == 'done' and probe['result']['segments'], probe
            report['probe'] = probe['result']
            post('/api/setup/complete', {})
            response = session.post(base + '/api/upload', params={'engine': 'whisper-local', 'device': 'CPU',
                                    'filename': 'setup-check.wav', 'language': 'auto'}, data=audio, timeout=30)
            response.raise_for_status()
            job = response.json()
            result = until(lambda: get('/api/speech?job=' + job['id']),
                           lambda r: r['job']['status'] in {'done', 'error'})
            assert result['job']['status'] == 'done', result['job']
            assert result['result']['segments']
            response = session.get(base + '/api/subtitles', params={'folder': result['job']['folder'], 'format': 'srt'}, timeout=10)
            response.raise_for_status()
            assert '-->' in response.text
            saved = read_json(app.HERE / 'config.local.json')
            restored = ComputeManager({**value, **saved}, app.HERE)
            assert restored.settings()['speech_device'] == 'CPU' and restored.model == args.model.resolve()
            assert get('/api/setup')['completed']
            report.update(passed=True, segments=len(result['result']['segments']), export='SRT',
                          settings_restored=True, isolated_workspace=str(workspace))
        finally:
            server.shutdown()
            thread.join()
            # This isolated CPU process was started by this script; never touch external services.
            state = read_json(app.HERE / 'runtime/backends/CPU.process.json', {})
            if state:
                try:
                    process = psutil.Process(state['pid'])
                    if process.create_time() == state['created'] and str(root) in ' '.join(process.cmdline()):
                        process.terminate()
                        process.wait(10)
                except psutil.NoSuchProcess:
                    pass
    output = app.REPOSITORY / 'dist/verification-setup.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
