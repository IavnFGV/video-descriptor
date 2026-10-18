"""Real Compose lifecycle check, with an isolated workspace and no model downloads."""
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory(prefix='vd-smoke-') as temporary:
        workspace = Path(temporary)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = {**os.environ, 'VIDEO_DESCRIPTOR_HOME': workspace.as_posix(),
               'VIDEO_DESCRIPTOR_PORT': str(port), 'GEMINI_API_KEY': '',
               'OLLAMA_BASE_URL': 'http://127.0.0.1:1'}
        command = ['docker', 'compose', '--project-name', 'vd-smoke-' + str(port)]

        def compose(*args):
            return subprocess.run([*command, *args], env=env, check=True,
                                  capture_output=True, text=True).stdout

        def get(path):
            with urllib.request.urlopen(f'http://127.0.0.1:{port}' + path, timeout=10) as response:
                return response.read()

        # Linux bind mounts must be writable by image UID 1000 on CI runners.
        workspace.chmod(0o777)
        for name in ('data/uploads', 'output/jobs/interrupted', '.devcontainer', 'cache'):
            (workspace / name).mkdir(parents=True)
            (workspace / name).chmod(0o777)
        (workspace / 'output/jobs').chmod(0o777)
        (workspace / 'output').chmod(0o777)
        job = workspace / 'output/jobs/interrupted/job.json'
        job.write_text(json.dumps({'id': 'interrupted', 'status': 'running'}))
        job.chmod(0o666)
        (workspace / 'output/result.txt').write_text('retained result', encoding='utf-8')
        (workspace / 'data/uploads/input.txt').write_text('retained input', encoding='utf-8')
        (workspace / '.devcontainer/model-prompts.json').write_text('{"translate":"retained prompt"}')
        (workspace / 'cache/marker').write_text('retained cache')
        try:
            compose('up', '-d', '--no-build', '--wait', '--wait-timeout', '90')
            assert json.loads(get('/health')) == {'status': 'ok'}
            assert b'<html' in get('/create')
            assert json.loads(get('/api/diagnostics'))['ollama']['status'] == 'unavailable'
            assert json.loads(job.read_text())['status'] == 'error'
            # Verify worker stays alive after its former 30-second idle timeout.
            time.sleep(33)
            compose('exec', '-T', 'app', 'python', '-c',
                    "from pathlib import Path; assert any(b'video_descriptor.jobs' in "
                    "p.read_bytes().split(b'\\0') for p in Path('/proc').glob('[0-9]*/cmdline'))")
            # Exercise a real queued subprocess without downloading weights: invalid media fails.
            pending = workspace / 'output/jobs/invalid'
            pending.mkdir()
            pending.chmod(0o777)
            task = pending / 'job.json'
            task.write_text(json.dumps({'id': 'invalid', 'status': 'queued', 'created': 1,
                                        'mode': 'audio', 'engine': 'whisper', 'title': '',
                                        'video': '/workspace/data/uploads/input.txt'}))
            task.chmod(0o666)
            deadline = time.monotonic() + 30
            while json.loads(task.read_text())['status'] != 'error':
                assert time.monotonic() < deadline, 'Worker did not process queued media'
                time.sleep(.5)
            assert 'Распознавание' in json.loads(task.read_text())['error']
            compose('stop')
            compose('up', '-d', '--no-build', '--force-recreate', '--wait', '--wait-timeout', '90')
            assert get('/output/result.txt') == b'retained result'
            assert (workspace / 'data/uploads/input.txt').read_text() == 'retained input'
            assert json.loads(get('/api/prompts'))['prompts']['translate'] == 'retained prompt'
            assert (workspace / 'cache/marker').read_text() == 'retained cache'
            assert json.loads(job.read_text())['status'] == 'error'
            # Terminate worker: supervisor must fail, and restart policy must restore health.
            compose('exec', '-T', 'app', 'python', '-c',
                    "import os,signal; from pathlib import Path; "
                    "[os.kill(int(p.parent.name),signal.SIGKILL) for p in "
                    "Path('/proc').glob('[0-9]*/cmdline') if "
                    "b'video_descriptor.jobs' in p.read_bytes().split(b'\\0')]")
            deadline = time.monotonic() + 45
            while True:
                state = json.loads(compose('ps', '--all', '--format', 'json'))
                if isinstance(state, list):
                    state = state[0]
                count = compose('ps', '-q', 'app')
                restarts = subprocess.check_output(['docker', 'inspect', '--format',
                                                    '{{.RestartCount}}', count.strip()], text=True)
                if int(restarts) > 0 and state.get('Health') == 'healthy':
                    break
                assert time.monotonic() < deadline, 'Worker failure did not recover'
                time.sleep(1)
            assert json.loads(get('/health'))['status'] == 'ok'
            print('PASS: HTTP, worker queue/error, idle, interruption, stop/recreate persistence, crash restart')
        except Exception:
            print(compose('logs', '--tail', '80'))
            raise
        finally:
            compose('down', '--timeout', '15')


if __name__ == '__main__':
    main()
