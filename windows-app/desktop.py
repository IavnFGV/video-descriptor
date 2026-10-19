"""Desktop connection policy. Reuses app.py; never terminates a backend process."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time

import app


def state_path(value):
    fingerprint = hashlib.sha256(value['workspace'].encode()).hexdigest()[:16]
    return app.HERE / 'runtime' / f'instance-{fingerprint}.json'


def identity(info, value):
    try:
        recorded = json.loads(state_path(value).read_text(encoding='utf-8'))
        return (info.get('app') == app.APP and info.get('workspace') == value['workspace']
                and info.get('installation') == app.installation_id()
                and info.get('desktop_protocol') == 1
                and bool(recorded['instance']) and info.get('instance') == recorded['instance'])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def connect(value, timeout=30):
    url = f'http://127.0.0.1:{value["port"]}'
    deadline = time.monotonic() + timeout
    child = None
    while True:
        try:
            info = app.fetch(url + '/health', timeout=1)
        except (OSError, ValueError):
            info = None
        if info is not None:
            if not identity(info, value):
                raise ValueError('Порт занят другим приложением или устаревшей версией. '
                                 'Закройте её самостоятельно; процессы не остановлены.')
            return {'url': url, 'instance': info['instance'], 'workspace': value['workspace'],
                    'installation': app.installation_id()}
        if child is None:
            # An occupied but unresponsive port must never trigger a second backend.
            with socket.socket() as probe:
                occupied = probe.connect_ex(('127.0.0.1', value['port'])) == 0
            if occupied:
                raise ValueError('Порт занят, но backend не отвечает. См. runtime/logs/app.log.')
            logs = app.HERE / 'runtime/logs'
            logs.mkdir(parents=True, exist_ok=True)
            with (logs / 'desktop-backend.log').open('ab') as log:
                child = subprocess.Popen(
                    [sys.executable, '-X', 'utf8', '-u', str(app.HERE / 'app.py'), '--no-browser'],
                    cwd=app.REPOSITORY, stdin=subprocess.DEVNULL, stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=0x08000000 if os.name == 'nt' else 0)
        if child.poll() not in (None, 0):
            raise ValueError('Backend завершился при запуске. См. runtime/logs/desktop-backend.log.')
        if time.monotonic() >= deadline:
            raise ValueError('Backend не готов за 30 секунд. См. runtime/logs/desktop-backend.log. '
                             'Повторите подключение; загрузка не прервана.')
        time.sleep(.2)


if __name__ == '__main__':
    try:
        print(json.dumps(connect(app.config()), ensure_ascii=False), flush=True)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
