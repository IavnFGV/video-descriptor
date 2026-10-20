"""Persistent, consent-driven component operations. Never mutate a live runtime."""
import base64
import hashlib
import json
import math
import os
import shutil
import subprocess
import tarfile
import threading
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

import requests
from model_download import checksum

from video_descriptor.jobs import read_json, write_json
from video_descriptor.ollama_connection import DEFAULT_URL, loopback_url, selected, workspace_file
from video_descriptor.platform_support import (
    lock_file,
    windows_powershell,
    windows_shell_environment,
)
from video_descriptor.translation_settings import protected_key

STATES = {'not_installed', 'installed', 'downloading', 'installing', 'verifying',
          'ready', 'error', 'update_available'}
BUSY = {'downloading', 'installing', 'verifying'}
NAMES = {'whisper': 'Whisper · распознавание', 'ollama': 'Ollama · языковые модели',
         'diarization': 'pyannote · говорящие'}


class Cancelled(RuntimeError):
    pass


def native_path(path):
    """Extended filesystem paths work without changing Windows long-path policy."""
    path = Path(path)
    if os.name != 'nt':
        return path
    value = str(path.resolve())
    if not value.startswith('\\\\?\\'):
        value = '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    return Path(value)


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(20):
        try:
            write_json(path, value)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(.05)


def safe_member(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError('Недопустимый путь в архиве компонента')
    return path


def extract(source, target, cancel):
    target.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            for item in archive.infolist():
                safe_member(item.filename)
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Ссылки в архиве запрещены')
            for item in archive.infolist():
                if cancel.is_set():
                    raise Cancelled('Установка остановлена. Можно повторить.')
                archive.extract(item, target)
    else:
        with tarfile.open(source, 'r:gz') as archive:
            for item in archive.getmembers():
                safe_member(item.name)
                if not (item.isfile() or item.isdir()):
                    raise ValueError('Ссылки и специальные файлы в архиве запрещены')
            for item in archive.getmembers():
                if cancel.is_set():
                    raise Cancelled('Установка остановлена. Можно повторить.')
                archive.extract(item, target, filter='data')


class ComponentManager:
    def __init__(self, setup, root=None):
        self.setup, self.manager, self.here = setup, setup.manager, setup.here
        self.root = Path(root) if root else Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'VideoDescriptor/ai-components'
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'state.json'
        self.manifest = read_json(self.here / 'component-manifest.json', {})
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.active = None
        self.process = None
        self.server = None
        saved = read_json(self.path, {})
        saved = saved if isinstance(saved, dict) else {}
        self.components = {key: saved[key] if isinstance(saved.get(key), dict) and saved[key].get('state') in STATES
                           else {'state': 'not_installed', 'message': 'Требуется настройка'} for key in NAMES}
        with (self.root / 'operation.lock').open('a+') as lease:
            try:
                lock_file(lease)
            except (BlockingIOError, PermissionError):
                pass  # Another application instance owns this operation; do not recover it.
            else:
                for item in self.components.values():
                    if item['state'] in BUSY:
                        item.update(state='error', message='Подготовка прервана перезапуском. Повторите: проверенные файлы сохранены.')
                    elif item['state'] == 'ready':
                        item.update(state='installed', message='Последняя проверка сохранена. Проверьте готовность в этом запуске.')
                self.save()
        # Selection is configuration, not something inferred from an old managed artifact.
        self.connection = selected(self.manager.value)
        self.manager.value.update(ollama_mode=self.connection['mode'], ollama_url=self.connection['url'])
        if self.manager.value.get('workspace'):
            atomic(workspace_file(self.manager.value['workspace']), self.connection)

    def save(self):
        atomic(self.path, self.components)

    def update(self, key, state=None, **fields):
        with self.lock:
            if state is not None:
                if state not in STATES:
                    raise ValueError('Неизвестное состояние компонента')
                fields['state'] = state
            self.components[key].update(fields)
            self.save()

    def snapshot(self):
        with self.lock:
            if not self.active:
                saved = read_json(self.path, {})
                if isinstance(saved, dict):
                    self.components.update({key: value for key, value in saved.items()
                                            if key in NAMES and isinstance(value, dict) and value.get('state') in STATES})
            rows = []
            for key, title in NAMES.items():
                item = dict(self.components[key])
                installed = (self.manager.model / 'config.json').is_file() if key == 'whisper' else bool(
                    self.manager.value.get('diarization_python') if key == 'diarization' else
                    shutil.which('ollama') or item.get('path'))
                if item['state'] == 'not_installed' and installed:
                    item.update(state='installed', message='Обнаружен компонент. Выполните проверку.')
                if (key == 'ollama' and selected(self.manager.value)['mode'] == 'managed' and item.get('path') and item.get('version') and item['state'] not in BUSY | {'error'}
                        and item['version'] != self.manifest.get('ollama', {}).get('version', item['version'])):
                    item.update(state='update_available', message='В этой версии приложения доступен новый проверенный runtime. Рабочая версия сохранена.')
                if key == 'ollama':
                    item.update(selected(self.manager.value))
                rows.append({'id': key, 'name': title, **item})
            return {'components': rows, 'active': self.active or next((key for key in NAMES if self.components[key]['state'] in BUSY), None), 'root': str(self.root),
                    'profiles': {key: self.manifest.get(key) for key in ('managed_python', 'ollama', 'diarization_model', 'ollama_models')},
                    'has_hf_token': (self.root / 'hf-token.dpapi').is_file(),
                    'ollama_connection': {**selected(self.manager.value), 'executable': self.existing_executable(),
                                          'service_url': self.manager.value.get('ollama_service_url', DEFAULT_URL)}}

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled('Остановлено. Повторите подготовку: проверенные файлы сохранены.')

    def download(self, profile, key):
        self.check_cancel()
        cache = self.root / 'downloads'
        cache.mkdir(exist_ok=True)
        target = cache / profile['sha256']
        if target.is_file() and checksum(target) == profile['sha256']:
            return target
        if shutil.disk_usage(cache).free < profile['bytes'] * 3 + 256 * 1024**2:
            raise ValueError('Недостаточно свободного места для загрузки и распаковки компонента')
        temporary = target.with_suffix('.part')
        count = temporary.stat().st_size if temporary.exists() else 0
        with requests.Session() as session:
            session.trust_env = False
            with session.get(profile['url'], headers={'Range': f'bytes={count}-'} if count else {},
                             stream=True, timeout=(15, 30)) as response:
                if response.status_code == 416:
                    temporary.unlink(missing_ok=True)
                    raise ValueError('Загрузка прервана на границе файла. Повторите загрузку.')
                response.raise_for_status()
                if response.status_code != 206:
                    count = 0
                elif not response.headers.get('Content-Range', '').startswith(f'bytes {count}-'):
                    raise ValueError('Сервер вернул неверное продолжение загрузки')
                with temporary.open('ab' if count else 'wb') as output:
                    for block in response.iter_content(1024**2):
                        self.check_cancel()
                        count += len(block)
                        if count > profile['bytes']:
                            raise ValueError('Размер загрузки превышает проверенный манифест')
                        output.write(block)
                        self.update(key, 'downloading', bytes=count, total=profile['bytes'], message='Загружаем компонент')
        self.update(key, 'verifying', message='Проверяем контрольную сумму')
        if count != profile['bytes'] or checksum(temporary) != profile['sha256']:
            temporary.unlink(missing_ok=True)
            raise ValueError('Контрольная сумма загрузки не совпала. Повторите установку.')
        temporary.replace(target)
        return target

    def run(self, command, key, timeout=1800, env=None):
        self.check_cancel()
        self.update(key, 'installing', message='Подготавливаем окружение' if 'pip' in command else 'Проверяем компонент')
        # Never persist subprocess output: pip/upstream diagnostics can contain credentials.
        with open(os.devnull, 'wb') as output:
            process = subprocess.Popen([str(arg) for arg in command], stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=output, env=env or {**{k: v for k, v in os.environ.items() if k.upper() not in {'PYTHONPATH', 'PYTHONHOME'}},
                                                    'PYTHONUTF8': '1', 'PIP_NO_INPUT': '1'},
                                       creationflags=0x08000000 if os.name == 'nt' else 0)
            self.process = process
            started = time.monotonic()
            try:
                while process.poll() is None:
                    self.check_cancel()
                    if time.monotonic() - started > timeout:
                        raise RuntimeError('Превышено время подготовки. Проверьте сеть и повторите.')
                    self.cancel.wait(.2)
                if process.returncode:
                    raise RuntimeError(f'Проверка/установка завершилась с кодом {process.returncode}. Рабочая конфигурация сохранена.')
            finally:
                if process.poll() is None:
                    process.terminate()  # Only this exact owned child; never taskkill/python/ollama by name.
                    process.wait(timeout=15)
                self.process = None

    def publish(self, changes):
        self.check_cancel()
        with self.manager._lock:
            config = self.here / 'config.local.json'
            original = config.read_bytes() if config.exists() else None
            try:
                local = json.loads(original.decode('utf-8-sig')) if original is not None else {}
                if not isinstance(local, dict):
                    raise TypeError
            except (ValueError, TypeError):
                raise ValueError('Локальные настройки повреждены. Файл сохранён; восстановите настройки перед подключением.') from None
            replacement = {**self.manager.value, **changes}
            connection = selected(replacement) if 'ollama_url' in changes or 'ollama_mode' in changes else None
            workspace = workspace_file(replacement['workspace']) if connection else None
            previous_workspace = workspace.read_bytes() if workspace and workspace.exists() else None
            try:
                atomic(config, {**local, **changes})
                if workspace:
                    atomic(workspace, connection)
            except OSError:
                if original is None:
                    config.unlink(missing_ok=True)
                else:
                    config.write_bytes(original)
                if workspace:
                    if previous_workspace is None:
                        workspace.unlink(missing_ok=True)
                    else:
                        workspace.write_bytes(previous_workspace)
                raise
            self.manager.value.update(changes)
            if connection:
                self.connection = connection
                os.environ['OLLAMA_BASE_URL'] = connection['url']

    def action(self, key, body):
        if key not in NAMES:
            raise ValueError('Неизвестный компонент')
        action = body.get('action', 'check')
        if action == 'cancel':
            if self.active != key:
                raise ValueError('У этого компонента нет активной операции')
            self.cancel.set()
            self.update(key, pending_action=None)
            return {'cancel_requested': True}
        if action == 'prepare' and key != 'ollama':
            raise ValueError('Автоматическая подготовка доступна для локального AI')
        if action not in {'install', 'check', 'pull', 'prepare', 'remove', 'connect', 'start_existing'}:
            raise ValueError('Неизвестное действие')
        if action in {'install', 'pull', 'prepare', 'remove', 'start_existing'} and body.get('confirmed') is not True:
            raise ValueError('Подтвердите загрузку или удаление управляемого компонента')
        if key == 'ollama' and action in {'install', 'prepare'} and body.get('mode') != 'managed':
            raise ValueError('Выберите режим «Установить управляемую Ollama» и подтвердите установку')
        if action in {'connect', 'start_existing'} and key != 'ollama':
            raise ValueError('Действие доступно только для Ollama')
        if key == 'diarization' and body.get('device', 'auto') not in {'auto', 'cpu', 'xpu'}:
            raise ValueError('Выберите Auto, CPU или XPU')
        with self.manager._lock:
            self.setup.guard()
            if self.active:
                raise RuntimeError('Дождитесь завершения текущей подготовки')
            saved_pending = self.components[key].get('pending_action')
            pending = body.get('resume', saved_pending if isinstance(saved_pending, dict) and saved_pending.get('workspace') == self.manager.value.get('workspace') and action != 'remove' else None)
            if pending is not None:
                from video_descriptor.construction import checked_folder
                if not isinstance(pending, dict) or pending.get('task') not in {'diarize', 'translate', 'notes'}:
                    raise ValueError('Выберите действие для записи')
                if (key == 'diarization') != (pending['task'] == 'diarize') or key == 'whisper':
                    raise ValueError('Действие не соответствует компоненту')
                checked_folder(Path(self.manager.value['workspace']), pending.get('folder'))
            lease = (self.root / 'operation.lock').open('a+')
            try:
                lock_file(lease)
            except (BlockingIOError, PermissionError):
                lease.close()
                raise RuntimeError('Компоненты настраиваются в другом экземпляре приложения') from None
            if action in {'install', 'pull', 'prepare'}:
                profile = self.manifest.get('whisper_model' if key == 'whisper' else 'diarization_model' if key == 'diarization' else 'ollama', {})
                self.update(key, download_consent=True, consent_revision=profile.get('revision') or profile.get('sha256'))
            self.update(key, pending_action={**pending, 'workspace': self.manager.value['workspace']} if pending else None, resumed_job=None)
            self.active = key
            self.manager.operation = 'components-' + key
            self.cancel.clear()
            self.update(key, 'verifying' if action == 'check' else 'installing', message='Начинаем подготовку', bytes=0, total=0, operation_id=uuid.uuid4().hex)

        def work():
            started = time.monotonic()
            try:
                if action == 'remove':
                    proof = self.remove(key)
                elif key == 'ollama':
                    proof = self.ollama(body, action)
                elif key == 'diarization':
                    proof = self.diarization(body, action)
                else:
                    proof = self.whisper(action)
                self.check_cancel()
                pending = self.components[key].get('pending_action')
                if pending and pending.get('workspace') == self.manager.value['workspace'] and action != 'remove':
                    from video_descriptor.jobs import start_worker
                    root = Path(self.manager.value['workspace'])
                    if pending['task'] == 'diarize':
                        from video_descriptor.diarization_postprocess import enqueue
                        job = enqueue(root, pending['folder'], self.manager.value)
                    else:
                        from video_descriptor.postprocess import enqueue
                        job = enqueue(root, pending['folder'], pending['task'], proof['model'], self.manager.value['ollama_url'], notes_model=proof['model'])
                    self.update(key, pending_action=None, resumed_job=job['id'])
                    start_worker(root)
                state = 'not_installed' if action == 'remove' else 'ready'
                message = 'Компонент удалён' if action == 'remove' else 'Проверка выполнена'
                if key == 'ollama' and action != 'remove' and not proof.get('generation_checked'):
                    state, message = 'installed', 'Подключение Ollama проверено. Выберите модель и проверьте генерацию.'
                self.update(key, state, message=message,
                            proof=proof, elapsed_seconds=round(time.monotonic() - started, 2))
            except Exception as exc:  # noqa: BLE001 — operation boundary; never leak upstream response/token.
                message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else 'Ошибка сети или доступа к файлам. Проверьте подключение и повторите.'
                self.update(key, 'error', message=message, error_type=type(exc).__name__, windows_error=getattr(exc, 'winerror', None), elapsed_seconds=round(time.monotonic() - started, 2))
            finally:
                with self.manager._lock:
                    self.active = None
                    self.manager.operation = None
                    lease.close()
        threading.Thread(target=work, name='component-' + key, daemon=True).start()
        return {'started': True, 'component': key}

    def api(self, endpoint, body=None, timeout=10):
        from setup_service import ollama_request
        if timeout == 10:
            return ollama_request(self.manager.value, endpoint, body)
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(self.manager.value['ollama_url'] + endpoint, json=body, timeout=(5, timeout))
            response.raise_for_status()
            return response.json()

    @staticmethod
    def existing_executable():
        candidates = [shutil.which('ollama'), str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Programs/Ollama/ollama.exe')]
        for value in candidates:
            if value:
                path = Path(value).resolve()
                if path.name.lower() == 'ollama.exe' and path.is_file():
                    return str(path)
        return None

    def inspect_ollama(self, url):
        from setup_service import ollama_request
        settings = {**self.manager.value, 'ollama_url': loopback_url(url)}
        version = ollama_request(settings, '/api/version')
        tags = ollama_request(settings, '/api/tags')
        if not isinstance(version, dict) or not isinstance(version.get('version'), str) or not isinstance(tags, dict) or not isinstance(tags.get('models'), list):
            raise TypeError('Сервис не вернул версию и список моделей Ollama')
        return version, tags['models']

    def connect_ollama(self, mode, url=None):
        if mode not in {'existing', 'service', 'managed'}:
            raise ValueError('Выберите режим подключения Ollama')
        if mode == 'managed':
            url = self.manager.value.get('ollama_managed_url')
            path = Path(self.components['ollama'].get('path') or '__missing__')
            if not url or path.resolve().parent != self.root.resolve() or read_json(path / '.managed.json', {}).get('component') != 'ollama':
                raise ValueError('Сначала явно установите управляемую Ollama')
        url = DEFAULT_URL if mode == 'existing' else loopback_url(url)
        try:
            version, models = self.inspect_ollama(url)
        except requests.RequestException:
            if mode == 'existing' and self.existing_executable():
                raise ValueError('Ollama установлена, но сервер выключен. Запустите её отдельной кнопкой и повторите подключение.') from None
            raise ValueError('Выбранная Ollama недоступна. Проверьте адрес и запустите сервер; автоматического переключения нет.') from None
        changes = {'ollama_mode': mode, 'ollama_url': url}
        if mode == 'service':
            changes['ollama_service_url'] = url
        self.publish(changes)
        if mode != 'managed':
            self.close()
        self.update('ollama', version=version['version'], endpoint=url, ownership='managed' if mode == 'managed' else 'external')
        return {'api_version': version, 'models': models, 'endpoint': url, 'mode': mode, 'generation_checked': False}

    def start_existing_ollama(self):
        # An explicit user action only. Never private-port or private-model-directory flags.
        try:
            return self.connect_ollama('existing')
        except ValueError:
            pass
        executable = self.existing_executable()
        if not executable:
            raise ValueError('Не найден проверяемый путь ollama.exe. Запустите Ollama самостоятельно.')
        if self.verify_signature(executable) != 'Valid':
            raise ValueError('Не удалось подтвердить цифровую подпись установленной Ollama. Запустите её самостоятельно.')
        import socket
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', 11434)) == 0:
                raise ValueError('Порт 11434 занят другим сервисом. Новый процесс не запущен.')
        subprocess.Popen([executable, 'serve'], env={**os.environ, 'OLLAMA_HOST': '127.0.0.1:11434'},
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=0x08000000 if os.name == 'nt' else 0)
        # This remains an external user service, including after Video Descriptor exits.
        for _ in range(100):
            self.check_cancel()
            try:
                return self.connect_ollama('existing')
            except ValueError:
                self.cancel.wait(.2)
        raise ValueError('Ollama не запустилась на 11434. Проверьте её окно и повторите подключение.')

    def ensure_ollama(self, install=False):
        if not install:
            try:
                version, _ = self.inspect_ollama(selected(self.manager.value)['url'])
                return version
            except requests.RequestException:
                mode = selected(self.manager.value)['mode']
                if mode == 'existing' and self.existing_executable():
                    raise ValueError('Ollama установлена, но сервер выключен. Запустите Ollama отдельным действием.') from None
                raise ValueError('Выбранный сервер Ollama недоступен. Повторите подключение; другой сервер не запускается.') from None
        profile = self.manifest['ollama']
        target = self.root / ('ollama-' + profile['version'])
        executable = target / 'ollama.exe'
        if not executable.is_file():
            archive = self.download(profile, 'ollama')
            staging = self.root / ('ollama-staging-' + uuid.uuid4().hex)
            extract(archive, staging, self.cancel)
            if not (staging / 'ollama.exe').is_file():
                raise ValueError('Дистрибутив Ollama не содержит исполняемый файл')
            self.verify_signature(staging / 'ollama.exe')
            atomic(staging / '.managed.json', {'component': 'ollama', 'sha256': profile['sha256']})
            staging.rename(target)
        if read_json(target / '.managed.json', {}).get('component') != 'ollama':
            raise ValueError('Не подтверждено владение управляемым runtime Ollama')
        endpoint = self.manager.value.get('ollama_managed_url')
        if endpoint and self.components['ollama'].get('path') == str(target):
            try:
                version, _ = self.inspect_ollama(endpoint)
                if version.get('version') != profile['version']:
                    raise requests.ConnectionError('Managed runtime version differs from pinned update')
                self.publish({'ollama_url': endpoint, 'ollama_mode': 'managed'})
                return version
            except requests.RequestException:
                pass
        import socket
        port = 11435
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                with socket.socket() as available:
                    available.bind(('127.0.0.1', 0))
                    port = available.getsockname()[1]
        endpoint = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'OLLAMA_HOST': f'127.0.0.1:{port}', 'OLLAMA_MODELS': str(self.root / 'ollama-models'), 'OLLAMA_NO_CLOUD': '1'}
        previous_server = self.server
        candidate = subprocess.Popen([str(executable), 'serve'], env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=0x08000000 if os.name == 'nt' else 0)
        try:
            for _ in range(100):
                self.check_cancel()
                if candidate.poll() is not None:
                    raise ValueError('Управляемая Ollama завершилась при запуске; прежнее подключение сохранено')
                try:
                    version, _ = self.inspect_ollama(endpoint)
                    self.publish({'ollama_url': endpoint, 'ollama_mode': 'managed', 'ollama_managed_url': endpoint})
                    self.server = candidate
                    self.update('ollama', path=str(target), version=profile['version'], endpoint=endpoint, ownership='managed', bytes_on_disk=self.size(target))
                    if previous_server and previous_server.poll() is None:
                        previous_server.terminate()
                        previous_server.wait(timeout=15)
                    return version
                except requests.RequestException:
                    self.cancel.wait(.2)
            raise ValueError('Управляемая Ollama не ответила после запуска; прежнее подключение сохранено')
        except Exception:
            if candidate.poll() is None:
                candidate.terminate()
                candidate.wait(timeout=15)
            raise

    def close(self):
        # Never stop an external service (even one explicitly started on 11434).
        if self.server and self.server.poll() is None:
            self.server.terminate()
            self.server.wait(timeout=15)
        self.server = None

    @staticmethod
    def verify_signature(executable):
        if os.name != 'nt':
            return 'NotSigned'
        result = subprocess.run([windows_powershell(), '-NoProfile', '-NonInteractive', '-Command',
                                 "$ErrorActionPreference='Stop'; $s=Get-AuthenticodeSignature -LiteralPath $env:VD_SIGNATURE_FILE; [Console]::Write($s.Status.ToString())"],
                                env=windows_shell_environment({'VD_SIGNATURE_FILE': str(executable)}), capture_output=True,
                                text=True, timeout=30, check=True, creationflags=0x08000000)
        if result.stdout.strip() not in {'Valid', 'NotSigned'}:
            raise ValueError('Цифровая подпись компонента недействительна')
        return result.stdout.strip()

    def ollama(self, body, action):
        if action == 'connect':
            return self.connect_ollama(body.get('mode'), body.get('url'))
        if action == 'start_existing':
            return self.start_existing_ollama()
        version = self.ensure_ollama(install=action in {'install', 'prepare'})
        model = body.get('model')
        if not model:
            if action in {'pull', 'prepare'}:
                raise ValueError('Выберите модель')
            return {'api_version': version, 'generation_checked': False}
        profiles = {item['name']: item for item in self.manifest.get('ollama_models', [])}
        if action in {'pull', 'prepare'}:
            if model not in profiles:
                raise ValueError('Выберите модель из каталога')
            if selected(self.manager.value)['mode'] == 'managed' and shutil.disk_usage(self.root).free < profiles[model]['bytes'] * 1.2:
                raise ValueError('Недостаточно свободного места для языковой модели')
            with requests.Session() as session:
                session.trust_env = False
                with session.post(self.manager.value['ollama_url'] + '/api/pull', json={'model': model, 'stream': True},
                                  stream=True, timeout=(10, 60)) as response:
                    response.raise_for_status()
                    success = False
                    for line in response.iter_lines():
                        self.check_cancel()
                        if not line:
                            continue
                        data = json.loads(line)
                        if data.get('error'):
                            raise ValueError('Ollama не смогла загрузить модель. Проверьте сеть и повторите.')
                        self.update('ollama', 'downloading', bytes=data.get('completed', 0), total=data.get('total', 0),
                                    message='Загружаем языковую модель')
                        success = data.get('status') == 'success'
                    if not success:
                        raise ValueError('Загрузка модели прервана. Повторите: Ollama продолжит загрузку.')
        self.update('ollama', 'verifying', message='Проверяем генерацию текста')
        tags = self.api('/api/tags')['models']
        if model not in {item['name'] for item in tags}:
            raise ValueError('Модель не найдена в Ollama')
        if 'completion' not in self.api('/api/show', {'model': model}).get('capabilities', []):
            raise ValueError('Модель не поддерживает генерацию текста')
        result = self.api('/api/generate', {'model': model, 'prompt': 'Reply with one word: ready.', 'stream': False,
                                          'think': False, 'options': {'num_predict': 32}}, timeout=180)
        self.check_cancel()
        if result.get('done') is not True or not str(result.get('response', '')).strip():
            raise ValueError('Модель не вернула текст при проверке')
        from setup_service import select_ollama
        task = body.get('task', 'translation')
        select_ollama(self.manager.value, model, task)
        self.update('ollama', model=model, version=version.get('version', ''), device='Ollama Auto')
        return {'version': version, 'model': model, 'task': task, 'generation_checked': True,
                'model_digest': next(item.get('digest') for item in tags if item['name'] == model)}

    @staticmethod
    def size(path):
        return sum(p.stat().st_size for p in native_path(path).rglob('*') if p.is_file() and not p.is_symlink())

    def token(self, value=None):
        path = self.root / 'hf-token.dpapi'
        if value:
            if not isinstance(value, str) or not value.startswith('hf_') or len(value) > 512:
                raise ValueError('Введите личный токен Hugging Face с правом чтения')
            encrypted = protected_key(value.encode())
            path.write_bytes(base64.b64encode(encrypted))
        if not path.is_file():
            return None
        return protected_key(base64.b64decode(path.read_bytes()), decrypt=True).decode()

    def hf_model(self, token):
        profile = self.manifest['diarization_model']
        target = self.root / ('community-1-' + profile['revision'])
        if target.is_dir() and self.verify_model(target, profile):
            return target
        staging = self.root / ('.community-1-' + profile['revision'])
        staging.mkdir(exist_ok=True)
        with requests.Session() as session:
            session.trust_env = False
            if shutil.disk_usage(self.root).free < sum(item['bytes'] for item in profile['files']) + 64 * 1024**2:
                raise ValueError('Недостаточно свободного места для модели говорящих')
            for item in profile['files']:
                self.check_cancel()
                path = staging / safe_member(item['name'])
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and self.verify_file(path, item):
                    continue
                temporary = path.with_suffix(path.suffix + '.part')
                with session.get(profile['source'] + '/resolve/' + profile['revision'] + '/' + item['name'],
                                 headers={'Authorization': 'Bearer ' + token} if token else {},
                                 stream=True, timeout=(15, 60)) as response:
                    if response.status_code in {401, 403}:
                        raise ValueError('Для загрузки модели требуется разрешение Hugging Face: примите условия community-1 и введите токен чтения.')
                    response.raise_for_status()
                    count = 0
                    with temporary.open('wb') as output:
                        for block in response.iter_content(1024**2):
                            self.check_cancel()
                            count += len(block)
                            if count > item['bytes']:
                                raise ValueError('Размер файла community-1 превышает манифест')
                            output.write(block)
                            self.update('diarization', 'downloading', bytes=count, total=item['bytes'], message='Загружаем модель говорящих')
                if not self.verify_file(temporary, item):
                    raise ValueError('Контрольная сумма community-1 не совпала')
                temporary.replace(path)
        if not self.verify_model(staging, profile):
            raise ValueError('Модель community-1 повреждена')
        atomic(staging / '.managed.json', {'component': 'diarization', 'revision': profile['revision']})
        if target.exists():
            target = self.root / ('community-1-' + profile['revision'] + '-' + uuid.uuid4().hex)
        staging.rename(target)
        return target

    @staticmethod
    def verify_file(path, item):
        if path.stat().st_size != item['bytes']:
            return False
        if 'sha256' in item:
            return checksum(path) == item['sha256']
        digest = hashlib.sha1(b'blob ' + str(item['bytes']).encode() + b'\0' + path.read_bytes()).hexdigest()
        return digest == item['git_blob']

    def verify_model(self, path, profile):
        return all((path / item['name']).is_file() and self.verify_file(path / item['name'], item) for item in profile['files'])

    def python(self):
        profile = self.manifest['managed_python']
        target = self.root / ('cpython-' + profile['version'])
        python = target / 'python/python.exe'
        if python.is_file():
            return python
        source = self.download(profile, 'diarization')
        staging = self.root / ('python-staging-' + uuid.uuid4().hex)
        extract(source, staging, self.cancel)
        if not (staging / 'python/python.exe').is_file():
            raise ValueError('Дистрибутив CPython повреждён')
        atomic(staging / '.managed.json', {'component': 'python', 'sha256': profile['sha256']})
        staging.rename(target)
        return python

    def diarization(self, body, action):
        from diarization_setup import choose_device, detect_adapters
        requested = body.get('device', 'auto')
        selected = choose_device(requested, detect_adapters() if requested == 'auto' else [])
        model = self.hf_model(self.token(body.get('token'))) if action == 'install' else Path(self.manager.value.get('diarization_model_directory', ''))
        if not (model / 'config.yaml').is_file():
            raise ValueError('Сначала подготовьте модель диаризации')
        if action == 'install' and shutil.disk_usage(self.root).free < 8 * 1024**3:
            raise ValueError('Для подготовки диаризации нужно не менее 8 ГиБ свободного места')
        warning = ''
        try:
            runtime, proof = self.diarization_runtime(selected, model, install=action == 'install')
        except (RuntimeError, ValueError) as exc:
            self.check_cancel()
            if requested != 'auto' or selected != 'xpu':
                raise
            warning = 'Intel GPU обнаружен, но проверка XPU не прошла. Проверен CPU. ' + str(exc)
            selected = 'cpu'
            runtime, proof = self.diarization_runtime(selected, model, install=action == 'install')
        self.check_cancel()
        self.publish({'diarization_python': str(runtime), 'diarization_model_directory': str(model),
                      'diarization_device': selected, 'diarization_requested_device': requested,
                      'diarization_setup_warning': warning, 'diarization_probe': proof})
        self.update('diarization', path=str(runtime.parent.parent), model=str(model), device=selected, requested_device=requested,
                    version=proof.get('torch', ''), fallback_reason=warning,
                    bytes_on_disk=self.size(runtime.parent.parent) + self.size(model))
        return proof

    def stage_python_runtime_libraries(self, destination):
        # PyTorch needs the app-local CRT even on a clean Windows installation.
        # Reuse reviewed installer files; never depend on a system redistributable.
        profile = read_json(self.here / 'release-inputs.json', {})['vcrt']
        source = self.here.parent / 'python'
        for item in profile['files']:
            name = item['name']
            if Path(name).name != name or not name.lower().endswith('.dll'):
                raise ValueError('Некорректный профиль библиотек Python')
            library = source / name
            if not library.is_file() or checksum(library) != item['sha256']:
                raise ValueError('Библиотеки Microsoft VC++ повреждены. Переустановите Video Descriptor.')
        destination.mkdir(parents=True, exist_ok=True)
        for item in profile['files']:
            self.check_cancel()
            target = destination / item['name']
            if target.is_file() and checksum(target) == item['sha256']:
                continue
            temporary = target.with_suffix('.dll.tmp')
            shutil.copyfile(source / item['name'], temporary)
            temporary.replace(target)

    def diarization_runtime(self, device, model, install):
        if install:
            base = self.python()
            # venv contains absolute paths: create at its final unique path, publish only
            # after inference; failed candidates never replace the previous environment.
            folder = self.root / ('pyannote-' + device + '-' + uuid.uuid4().hex)
            folder.mkdir()
            atomic(folder / '.managed.json', {'component': 'diarization', 'device': device})
            self.run([base, '-m', 'venv', folder], 'diarization')
            python = folder / 'Scripts/python.exe'
            # PyTorch explicitly adds this venv-local directory to DLL search.
            self.stage_python_runtime_libraries(folder / 'Library/bin')
            requirements = self.here / ('requirements-pyannote-' + device + '.lock')
            self.run([python, '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check', '--index-url',
                      'https://pypi.org/simple', '--prefix', native_path(folder), '-r', requirements], 'diarization')
            self.run([python, '-m', 'pip', 'check'], 'diarization')
        else:
            python = Path(self.manager.value.get('diarization_python', ''))
        if not python.is_file():
            raise ValueError('Окружение диаризации отсутствует. Нажмите «Подготовить диаризацию».')
        proof_dir = self.root / 'checks' / uuid.uuid4().hex
        proof_dir.mkdir(parents=True)
        self.update('diarization', 'verifying', message='Проверяем диаризацию · ' + device.upper())
        self.run([python, self.here / 'diarization_worker.py', '--model', model, '--device', device,
                  '--audio', self.here / 'samples/speech-check.wav', '--output', proof_dir / 'result.json',
                  '--progress', proof_dir / 'progress.json'], 'diarization', timeout=600)
        proof = read_json(proof_dir / 'result.json', {})
        requirements = self.here / ('requirements-pyannote-' + device + '.lock')
        proof['requirements_sha256'] = checksum(requirements)
        proof['model_revision'] = self.manifest['diarization_model']['revision']
        turns = proof.get('turns', [])
        if proof.get('device') != device or not turns or any(
                not row.get('speaker') or not all(math.isfinite(row.get(k, -1)) for k in ('start', 'end')) or
                not 0 <= row['start'] < row['end'] <= proof['duration'] + .1 for row in turns):
            raise ValueError('Проверка диаризации не вернула корректные интервалы и идентификаторы голосов')
        return python, proof

    def whisper(self, action):
        from model_download import download_profile
        from setup_service import inspect_model
        model = self.manager.model
        candidate = self.manager
        changed = False
        if action == 'install':
            try:
                inspect_model(str(model), self.here)
            except ValueError:
                def progress(done, total, name):
                    self.check_cancel()
                    self.update('whisper', 'downloading', bytes=done, total=total, message='Загружаем модель распознавания')
                staging, target = download_profile(self.manifest['whisper_model'], self.root / 'models', progress)
                inspect_model(str(staging), self.here)
                if target.exists():
                    try:
                        inspect_model(str(target), self.here)
                    except ValueError:
                        target = target.with_name(target.name + '-' + uuid.uuid4().hex)
                if not target.exists():
                    staging.rename(target)
                model = target
                changed = True
                candidate = type(self.manager)({**self.manager.value, 'whisper_model_directory': str(model),
                                               'whisper_model_sha256': inspect_model(str(model), self.here)['sha256']}, self.here)
        inspected = inspect_model(str(model), self.here)
        self.update('whisper', 'verifying', message='Проверяем распознавание на встроенной записи')
        plan = candidate.make_plan(self.manager.settings()['speech_device'], operation='components-whisper')
        backend = candidate.backends[plan['selected']]
        audio = (self.here / 'samples/speech-check.wav').read_bytes()
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(backend['url'] + '/transcribe', data=audio,
                                    headers={'X-Whisper-Model': 'small', 'X-Language': 'auto'}, timeout=(5, 180))
            response.raise_for_status()
            data = response.json()
        if not isinstance(data.get('segments'), list) or not data['segments']:
            raise ValueError('Проверочный фрагмент не вернул речь. Повторите проверку.')
        self.check_cancel()
        if changed:
            self.setup.apply(str(model), downloading=True)
        self.update('whisper', model=str(model), device=plan['selected'], version='small FP16', bytes_on_disk=inspected['bytes'])
        return {'device': plan['selected'], 'model_sha256': inspected['sha256'],
                'audio_sha256': hashlib.sha256(audio).hexdigest(), 'segments': len(data['segments'])}

    def remove(self, key):
        item = self.components[key]
        path = Path(item.get('path', ''))
        if not path.is_absolute() or path.resolve().parent != self.root.resolve() or path.is_symlink() or path.is_junction():
            raise ValueError('Можно удалить только компонент, установленный этим приложением')
        marker = read_json(path / '.managed.json', {})
        if marker.get('component') != key:
            raise ValueError('Компонент не принадлежит приложению')
        if key == 'ollama' and selected(self.manager.value)['mode'] != 'managed':
            raise ValueError('Внешний сервис не принадлежит Video Descriptor и не удаляется приложением')
        if key == 'ollama' and self.server and self.server.poll() is None:
            self.server.terminate()
            self.server.wait(timeout=15)
        if key == 'diarization':
            self.publish({'diarization_python': '', 'diarization_probe': {}})
        shutil.rmtree(native_path(path))
        self.update(key, path='', version='', proof={}, bytes_on_disk=0)
        return {'removed': True, 'models_retained': True}
