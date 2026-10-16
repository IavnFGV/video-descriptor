"""Loopback OpenVINO workers; model loading never installs packages or downloads weights."""
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .action_history import record
from .device_policy import DEVICES, candidates, requested_device
from .jobs import read_json, write_json
from .platform_support import lock_file


class BackendUnavailable(RuntimeError):
    pass


def pending_process(state):
    """A timed-out compilation can still be alive, including after a UI restart."""
    if not state:
        return False
    import psutil
    try:
        process = psutil.Process(state['pid'])
        return process.is_running() and process.create_time() == state['created']
    except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
        return False


def engine_info(backend, timeout=1):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(backend['url'] + '/health', timeout=timeout) as response:
            info = json.load(response)
        device = backend['device']
        expected = {'protocol': 1, 'device': device, 'model': 'small', 'multilingual': True,
                    'pipeline': 'static' if device == 'NPU' else 'dynamic', 'num_beams': 1}
        if (not isinstance(info, dict) or any(info.get(k) != v for k, v in expected.items())
                or info.get('word_timestamps', False) or not info.get('model_sha256')):
            raise ValueError('Worker profile mismatch')
        return info
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise BackendUnavailable(f'{backend["device"]}: обработчик недоступен или профиль не совпал') from exc


def ensure_backend(backend, runtime, *, timeout=180):
    try:
        return engine_info(backend)
    except BackendUnavailable:
        pass
    runtime = Path(runtime)
    runtime.mkdir(parents=True, exist_ok=True)
    lock = (runtime / f'{backend["device"]}.start.lock').open('a+')
    try:
        try:
            lock_file(lock)
        except BlockingIOError:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    return engine_info(backend)
                except BackendUnavailable:
                    time.sleep(.25)
            raise BackendUnavailable('Другой процесс не смог подготовить ' + backend['device']) from None
        try:
            return engine_info(backend)
        except BackendUnavailable:
            pass
        state_path = runtime / f'{backend["device"]}.process.json'
        if pending_process(read_json(state_path)):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    return engine_info(backend)
                except BackendUnavailable:
                    if not pending_process(read_json(state_path)):
                        break
                    time.sleep(.25)
            else:
                raise BackendUnavailable(f'{backend["device"]}: предыдущая загрузка ещё работает; см. журнал')
        # Reserve-check before compiling; never start on an occupied port with unknown profile.
        from urllib.parse import urlsplit
        parsed = urlsplit(backend['url'])
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                if os.name == 'nt':
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind(('127.0.0.1', parsed.port))
        except OSError:
            raise BackendUnavailable(f'{backend["device"]}: порт занят другим обработчиком') from None
        command = backend.get('command')
        if not command or not Path(command[0]).is_file():
            raise BackendUnavailable(f'{backend["device"]}: не подготовлен OpenVINO Python')
        record('device_loading', device=backend['device'], stage='speech')
        with (runtime / f'{backend["device"]}.log').open('ab') as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT,
                                       env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
                                       creationflags=0x08000000 if os.name == 'nt' else 0)
        import psutil
        try:
            write_json(state_path, {'pid': process.pid, 'created': psutil.Process(process.pid).create_time()})
        except psutil.NoSuchProcess:
            raise BackendUnavailable(f'{backend["device"]}: обработчик завершился при запуске') from None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                info = engine_info(backend)
                record('device_ready', device=backend['device'], stage='speech', model_sha256=info['model_sha256'])
                return info
            except BackendUnavailable:
                if process.poll() is not None:
                    raise BackendUnavailable(f'{backend["device"]}: загрузка завершилась с кодом {process.returncode}; см. журнал') from None
                time.sleep(.25)
        raise BackendUnavailable(f'{backend["device"]}: модель ещё не готова; процесс не остановлен, см. журнал')
    finally:
        lock.close()


def plan(requested, capabilities, backends, runtime):
    requested = requested_device(requested)
    order = candidates(requested, capabilities)
    reasons = [{'device': d, 'reason': capabilities.get(d, {}).get('reason', 'не найден')}
               for d in (DEVICES if requested == 'AUTO' else (requested,)) if d not in order]
    for device in order:
        try:
            info = ensure_backend(backends[device], runtime)
            return {'version': 1, 'requested': requested, 'selected': device, 'engine': info,
                    'backends': [backends[d] for d in order], 'runtime': str(runtime),
                    'selection_reasons': reasons}
        except BackendUnavailable as exc:
            reasons.append({'device': device, 'reason': str(exc)})
            if requested != 'AUTO':
                raise
            record('device_skipped', requested=requested, device=device, reason='startup_failed', stage='speech')
    raise BackendUnavailable('Не удалось подготовить распознавание. ' + '; '.join(r['reason'] for r in reasons))
