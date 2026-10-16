"""Native settings, discovery and preparation for the local speech backends."""
import concurrent.futures
import json
import os
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlsplit

from video_descriptor.action_history import record
from video_descriptor.device_policy import DEVICES, requested_device, select
from video_descriptor.jobs import read_json, write_json
from video_descriptor.local_backends import BackendUnavailable, engine_info, plan


class ComputeManager:
    def __init__(self, value, here):
        self.value = value
        self.here = Path(here)
        self.runtime = self.here / 'runtime/backends'
        self.settings_file = Path(value['workspace']) / '.devcontainer/compute-settings.json'
        worker = Path(value['npu_worker_directory'])
        npu_python = worker / '.venv-npu/Scripts/python.exe'
        bundled = self.here.parent / 'python/python.exe'
        python = Path(value.get('openvino_python') or (bundled if bundled.is_file() else npu_python))
        original_model = worker / 'OpenVINO-whisper-small-fp16-ov'
        model = Path(value.get('whisper_model_directory') or original_model)
        self.python, self.model = python, model
        self.backends = {}
        for device, port in [('NPU', 8766), ('GPU', 8768), ('CPU', 8767)]:
            url = value.get(device.lower() + '_url', f'http://127.0.0.1:{port}')
            port = urlsplit(url).port or 80
            external_npu = (device == 'NPU' and npu_python.is_file()
                            and (worker / 'whisper_npu_server.py').is_file()
                            and model.resolve() == original_model.resolve())
            script = worker / 'whisper_npu_server.py' if external_npu else self.here / 'whisper_worker.py'
            args = ['--model-name', 'small', '--bind', '127.0.0.1'] if external_npu else ['--device', device]
            self.backends[device] = {'device': device,
                                    'url': url,
                                    'command': [str(npu_python if external_npu else python), '-X', 'utf8', '-u',
                                                str(script), '--model', str(original_model if external_npu else model),
                                                *args, '--port', str(port)]}
            if value.get('whisper_model_sha256'):
                self.backends[device]['expected_model_sha256'] = value['whisper_model_sha256']
        self._inventory = None
        self._lock = threading.RLock()
        self.preparing = False
        self.last_error = ''
        self.failed = {}

    def settings(self):
        return {'speech_device': requested_device(read_json(self.settings_file, {}).get('speech_device', 'AUTO'))}

    def save(self, changes):
        if not isinstance(changes, dict):
            raise TypeError('Ожидается объект настроек устройства')
        device = requested_device(changes.get('speech_device'))
        with self._lock:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            write_json(self.settings_file, {'speech_device': device})
        record('settings_changed', requested=device, stage='speech')
        return self.settings()

    def inventory(self):
        with self._lock:
            if self._inventory is None:
                try:
                    result = subprocess.run([str(self.python), '-X', 'utf8', str(self.here / 'whisper_worker.py'),
                                             '--model', str(self.model), '--inventory'],
                                            capture_output=True, text=True, encoding='utf-8', timeout=20, check=True,
                                            creationflags=0x08000000 if os.name == 'nt' else 0)
                    self._inventory = json.loads(result.stdout)
                except (OSError, ValueError, subprocess.SubprocessError):
                    self._inventory = {'devices': [], 'model_present': False}
            return self._inventory

    def capabilities(self):
        inventory = self.inventory()
        detected = {d.split('.')[0] for d in inventory['devices']}

        def inspect(device):
            try:
                info = engine_info(self.backends[device], timeout=.5)
                return device, {'available': True, 'ready': True, 'engine': info, 'reason': 'Готово'}
            except BackendUnavailable:
                available = device in detected and inventory['model_present'] and device not in self.failed
                reason = self.failed.get(device) or ('Модель не загружена' if available else
                         'Подключите модель' if not inventory['model_present'] else 'Нет совместимого устройства или runtime')
                return device, {'available': available, 'ready': False, 'reason': reason}
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            return dict(pool.map(inspect, DEVICES))

    def snapshot(self):
        settings = self.settings()
        caps = self.capabilities()
        try:
            selected = select(settings['speech_device'], caps)
        except ValueError:
            selected = None
        return {'settings': settings, 'capabilities': caps, 'selected': selected,
                'preparing': self.preparing, 'error': self.last_error}

    def make_plan(self, requested):
        resolved = plan(requested, self.capabilities(), self.backends, self.runtime)
        self.failed.update({r['device']: r['reason'] for r in resolved['selection_reasons']})
        record('device_selected', requested=resolved['requested'], device=resolved['selected'],
               stage='speech', model_sha256=resolved['engine']['model_sha256'])
        return resolved

    def prepare(self):
        with self._lock:
            if self.preparing:
                return {'status': 'loading'}
            requested = self.settings()['speech_device']
            self.preparing, self.last_error = True, ''
            self.failed.clear()

        def work():
            try:
                self.make_plan(requested)
            except (BackendUnavailable, ValueError) as exc:
                self.last_error = str(exc)
            finally:
                self.preparing = False
        threading.Thread(target=work, name='prepare-speech-backend', daemon=True).start()
        return {'status': 'loading', 'requested': requested}
