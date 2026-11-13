"""Native launcher for the existing application; owns an isolated workspace only."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import importlib.metadata
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent
sys.path.insert(0, str(REPOSITORY))
sys.path.insert(0, str(HERE))
APP = 'video-descriptor-windows'
VERSION = json.loads((HERE / 'release-inputs.json').read_text(encoding='utf-8'))['version']
try:
    BUILD = int((REPOSITORY / 'BUILD').read_text(encoding='ascii').strip())
except (OSError, ValueError):
    BUILD = None
START_LOCK = threading.Lock()
LOGGER = logging.getLogger(__name__)


def installation_id():
    return hashlib.sha256(str(HERE.resolve()).encode()).hexdigest()


class NativeHTTPServer(ThreadingHTTPServer):
    request_queue_size = 32  # Concurrent startup checks must not drop loopback connections.
    # POSIX needs SO_REUSEADDR to restart while closed connections are in
    # TIME_WAIT. Windows keeps SO_EXCLUSIVEADDRUSE and must not allow reuse.
    allow_reuse_address = os.name != 'nt'

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def config():
    value = json.loads((HERE / 'config.example.json').read_text(encoding='utf-8'))
    local = Path(os.environ.get('VIDEO_DESCRIPTOR_CONFIG', str(HERE / 'config.local.json')))
    if local.exists():
        value.update(json.loads(local.read_text(encoding='utf-8')))
    if type(value['port']) is not int or not 1024 <= value['port'] <= 65535:
        raise ValueError('Некорректный порт приложения')
    for key in ('npu_url', 'cpu_url', 'gpu_url'):
        if key not in value:
            continue
        parsed = urlsplit(value[key])
        if (parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {'', '/'}):
            raise ValueError(f'{key}: в прототипе разрешён только локальный HTTP-сервис')
        value[key] = value[key].rstrip('/')
    from video_descriptor.ollama_connection import endpoint_url
    value['ollama_url'] = endpoint_url(value['ollama_url'])
    if value.get('records_directory'):
        from storage_service import local_folder
        workspace = local_folder(value['records_directory'])
    else:
        workspace = (HERE / value['workspace']).resolve()
        workspace.relative_to((HERE / 'runtime').resolve())
    value['workspace'] = str(workspace)
    worker = value['npu_worker_directory']
    value['npu_worker_directory'] = str(Path(worker) if worker else Path.home() / 'Downloads' / 'windows-benchmark')
    return value


def fetch(url, timeout=2):
    # Ignore proxy environment for loopback-only service contracts.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=timeout) as response:
        return json.load(response)


def expected_npu(info):
    return isinstance(info, dict) and not info.get('word_timestamps', False) and all(info.get(key) == value for key, value in {
        'protocol': 1, 'device': 'NPU', 'model': 'small', 'multilingual': True,
        'pipeline': 'static', 'num_beams': 1}.items())


def service(url, kind):
    try:
        data = fetch(url + ('/health' if kind == 'npu' else '/api/tags'))
        if not isinstance(data, dict):
            raise TypeError('Сервис вернул неожиданный JSON')
        if kind == 'npu' and not expected_npu(data):
            return {'ready': False, 'message': 'На порту другой профиль Whisper; нужен small/NPU/static/beam=1'}
        return {'ready': True, 'details': data}
    except (OSError, ValueError, TypeError, urllib.error.URLError) as exc:
        return {'ready': False, 'message': 'Сервис недоступен: ' + str(exc)}


def ffmpeg_path():
    if path := shutil.which('ffmpeg'):
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def doctor(value):
    import psutil
    from setup_service import ollama_status

    from video_descriptor.diarization_postprocess import status as diarization_status
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        npu = pool.submit(service, value['npu_url'], 'npu')
        ollama = pool.submit(ollama_status, value)
        npu, ollama = npu.result(), ollama.result()
    packages = {}
    for name in ('pydantic', 'requests', 'faster-whisper', 'av', 'opencv-python-headless', 'psutil', 'imageio-ffmpeg'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    worker = Path(value['npu_worker_directory'])
    python = worker / '.venv-npu' / 'Scripts' / 'python.exe'
    model = worker / 'OpenVINO-whisper-small-fp16-ov'
    state_path = HERE / 'runtime' / 'npu-start.json'
    try:
        startup = json.loads(state_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        startup = None
    return {'app': APP, 'version': VERSION, 'build': BUILD, 'workspace': value['workspace'],
            'python': sys.version.split()[0], 'packages': packages,
            'ffmpeg': ffmpeg_path(), 'probe': 'ffprobe' if shutil.which('ffprobe') else 'PyAV',
            'ram_gib': round(psutil.virtual_memory().total / 1024**3, 1),
            'free_disk_gib': round(shutil.disk_usage(HERE).free / 1024**3, 1),
            'cpu': os.environ.get('PROCESSOR_IDENTIFIER', 'unknown'),
            'npu': npu, 'ollama': ollama, 'npu_startup': startup,
            'can_start_npu': python.is_file() and (worker / 'whisper_npu_server.py').is_file() and (model / 'config.json').is_file(),
            'diarization': diarization_status(value),
            'model_downloads': True}


def environment(value):
    os.environ.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                      PYTHONPATH=str(REPOSITORY) + os.pathsep + os.environ.get('PYTHONPATH', ''),
                      SPEECH_NPU_URL=value['npu_url'], WHISPER_HTTP_URL=value['npu_url'],
                      WHISPER_BACKEND='openvino-http', OLLAMA_BASE_URL=value['ollama_url'],
                      OLLAMA_MODEL=value['ollama_model'],
                      HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    os.environ['VIDEO_DESCRIPTOR_EVENTS'] = str(Path(value.get('application_log_directory') or HERE / 'runtime/logs') / 'events.jsonl')
    os.environ['VIDEO_DESCRIPTOR_WORKSPACE'] = value['workspace']
    if value['diarization_python']:
        os.environ['VIDEO_DESCRIPTOR_DIARIZATION_PYTHON'] = value['diarization_python']
    executable = ffmpeg_path()
    if executable and not shutil.which('ffmpeg'):
        # media.run accepts a concrete executable; no global PATH or system install.
        os.environ['VIDEO_DESCRIPTOR_FFMPEG'] = executable


def start_npu(value):
    with START_LOCK:
        status = service(value['npu_url'], 'npu')
        if status['ready']:
            return {'status': 'ready', 'reused': True}
        parsed = urlsplit(value['npu_url'])
        if parsed.hostname != '127.0.0.1' or parsed.port != 8766:
            raise ValueError('Автозапуск разрешён только для 127.0.0.1:8766')
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                if os.name == 'nt':
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind(('127.0.0.1', 8766))
        except OSError:
            raise ValueError('Порт 8766 занят другим или загружающимся сервисом; второй экземпляр не запущен') from None
        worker = Path(value['npu_worker_directory'])
        python = worker / '.venv-npu' / 'Scripts' / 'python.exe'
        model = worker / 'OpenVINO-whisper-small-fp16-ov'
        if not python.is_file() or not (model / 'config.json').is_file():
            raise ValueError('Не найдены существующие NPU Python/модель; ничего не скачано')
        state_path = HERE / 'runtime' / 'npu-start.json'
        if state_path.exists():
            import psutil
            previous = json.loads(state_path.read_text(encoding='utf-8'))
            try:
                process = psutil.Process(previous['pid'])
                if abs(process.create_time() - previous['created']) < .1:
                    return {'status': 'loading', 'pid': process.pid}
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        logs = HERE / 'runtime' / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / 'npu.log').open('ab') as log:
            process = subprocess.Popen([str(python), '-X', 'utf8', '-u', str(worker / 'whisper_npu_server.py'),
                                        '--model', str(model), '--model-name', 'small', '--bind', '127.0.0.1', '--port', '8766'],
                                       cwd=worker, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=0x08000000 if os.name == 'nt' else 0)
        import psutil
        state_path.write_text(json.dumps({'pid': process.pid, 'created': psutil.Process(process.pid).create_time()}), encoding='utf-8')
        def observe_exit():
            code = process.wait()
            # Preserve the failure for diagnosis; never kill or restart external services.
            try:
                state = json.loads(state_path.read_text(encoding='utf-8'))
                if state.get('pid') == process.pid:
                    state.update(exit_code=code, finished=time.time())
                    temporary = state_path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(state), encoding='utf-8')
                    temporary.replace(state_path)
            except OSError:
                LOGGER.exception('Could not save NPU startup status')
        threading.Thread(target=observe_exit, name='npu-startup-monitor', daemon=True).start()
        return {'status': 'loading', 'pid': process.pid}


def make_handler(value, instance, updates=None):
    if updates is None:
        from updates import UpdateChecker
        updates = UpdateChecker(VERSION, BUILD, Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'VideoDescriptor/update-cache.json',
                                supported=not value.get('development', False))
    from compute import ComputeManager
    from setup_service import (
        SetupService,
        choose_folder,
        inspect_model,
        ollama_status,
        select_ollama,
        validate_ollama_model,
    )

    from video_descriptor.action_history import record
    from video_descriptor.jobs import enqueue, read_json, start_worker, write_json
    manager = ComputeManager(value, HERE) if 'npu_worker_directory' in value else None
    setup = SetupService(manager, HERE) if manager is not None else None
    from component_manager import ComponentManager
    components = ComponentManager(setup, root=value.get('ai_components_directory')) if setup else None
    from storage_service import StorageService
    storage = StorageService(setup, components) if setup else None
    if setup:
        setup.bootstrap()
    from video_descriptor.serve import RangeRequestHandler

    class Handler(RangeRequestHandler):
        def parse_request(self):
            if not super().parse_request():
                return False
            # Reject DNS rebinding and cross-site requests before any native/inherited API.
            port = self.server.server_port
            hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
            origin = self.headers.get('Origin')
            if (self.headers.get('Host') not in hosts
                    or (origin and origin not in {f'http://{host}' for host in hosts})
                    or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
                self.close_connection = True
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if 0 < length <= 8192:
                        self.connection.settimeout(2)
                        self.rfile.read(length)
                except (ValueError, OSError):
                    pass
                self.send_error(403, 'Only local application requests are allowed')
                return False
            return True

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/api/updates':
                return self.json_response(200, updates.snapshot())
            if path == '/health':
                development = {}
                version = VERSION
                if value.get('development'):
                    version = read_json(HERE / 'release-inputs.json', {}).get('version', VERSION)
                    development = {'development': True, 'source_commit': os.getenv('VIDEO_DESCRIPTOR_DEV_COMMIT', '')}
                return self.json_response(200, {'app': APP, 'version': version, 'build': BUILD,
                                               'instance': instance, 'workspace': value['workspace'],
                                               'installation': installation_id(), 'desktop_protocol': 1, **development})
            if path == '/api/doctor':
                result = doctor(value)
                if manager is not None:
                    result['compute'] = manager.snapshot()
                return self.json_response(200, result)
            if path == '/api/compute-settings' and manager is not None:
                return self.json_response(200, manager.snapshot())
            if path == '/api/storage' and storage is not None:
                return self.json_response(200, storage.snapshot())
            if path == '/api/setup' and setup is not None:
                return self.json_response(200, setup.snapshot())
            if path == '/api/components' and components is not None:
                return self.json_response(200, components.snapshot())
            if path == '/api/setup/diagnostics' and setup is not None:
                return self.json_response(200, setup.diagnostics())
            if path == '/api/setup/ollama' and setup is not None:
                return self.json_response(200, ollama_status({**value, 'ollama_url': parse_qs(urlsplit(self.path).query, keep_blank_values=True).get('endpoint', [value['ollama_url']])[0]}))
            if path == '/api/native/events':
                event_file = Path(os.getenv('VIDEO_DESCRIPTOR_EVENTS', str(HERE / 'runtime/logs/events.jsonl')))
                events = []
                if event_file.exists():
                    with event_file.open('rb') as source:
                        source.seek(0, 2)
                        source.seek(max(0, source.tell() - 128 * 1024))
                        for line in source.read().decode('utf-8', errors='replace').splitlines()[-80:]:
                            try:
                                from video_descriptor.action_history import describe
                                event = json.loads(line)
                                events.append({**event, 'label': describe(event)})
                            except (ValueError, KeyError, TypeError):
                                continue  # Ignore truncated or invalid event records.
                return self.json_response(200, events)
            if path in {'/', '/native.js', '/native.css', '/updates.js', '/help/ollama', '/help/lmstudio'}:
                name = {'/': 'index.html', '/native.js': 'app.js', '/native.css': 'app.css', '/updates.js': 'updates.js', '/help/ollama': 'help.html', '/help/lmstudio': 'help.html'}[path]
                if path in {'/help/ollama', '/help/lmstudio'}:
                    from markdown_it import MarkdownIt
                    provider = 'Ollama' if path == '/help/ollama' else 'LM Studio'
                    document = 'ollama-windows.md' if path == '/help/ollama' else 'lmstudio-windows.md'
                    content = MarkdownIt().enable('table').render((REPOSITORY / 'docs' / document).read_text(encoding='utf-8'))
                    navigation = ('<nav class="vd-actions" aria-label="Возврат в приложение">'
                                  '<a class="vd-button" href="/#settings">Вернуться к настройкам AI</a>'
                                  '<a class="vd-button" href="/#records">К записям</a></nav>')
                    body = ('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                            f'<title>{provider} — инструкция</title><link rel="stylesheet" href="/native.css">'
                            '<body><main class="card vd-prose">' + navigation + content + navigation + '</main></body></html>').encode('utf-8')
                else:
                    body = (HERE / 'ui' / name).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', {'html': 'text/html', 'js': 'text/javascript', 'css': 'text/css'}[name.rsplit('.', 1)[-1]] + '; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
                return
            return super().do_GET()

        def do_POST(self):
            # Update requests never take device/job locks or wait for GitHub.
            if urlsplit(self.path).path == '/api/updates/check':
                if (self.headers.get('X-App-Instance') != instance
                        or self.headers.get('Content-Length', '0') != '0'
                        or self.headers.get('Transfer-Encoding')):
                    self.close_connection = True
                    return self.json_response(403, {'error': 'Откройте приложение заново'})
                updates.request()
                return self.json_response(202, updates.snapshot())
            if manager is not None:
                with manager._lock:
                    return self.handle_post()
            return self.handle_post()

        def handle_post(self):
            path = urlsplit(self.path).path
            if storage and storage.blocked() and path not in {'/api/setup/storage', '/api/native/stop'}:
                self.close_connection = True
                return self.json_response(409, {'error': 'Перенос данных: дождитесь завершения и полностью перезапустите приложение'})
            if path == '/api/speech-run' and manager is not None:
                try:
                    if self.headers.get('Origin') and urlsplit(self.headers['Origin']).netloc != self.headers.get('Host'):
                        return self.json_response(403, {'error': 'Запрос должен исходить из приложения'})
                    length = int(self.headers.get('Content-Length', '0'))
                    if self.headers.get_content_type() != 'application/json' or not 0 < length <= 400_000:
                        raise ValueError('Ожидается JSON параметров распознавания')
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict) or body.get('engine') != 'whisper-local':
                        raise ValueError('Выберите локальное распознавание в настройках приложения')
                    if manager.operation:
                        raise RuntimeError('Дождитесь завершения настройки')
                    from video_descriptor.speech import enqueue_existing, source_path
                    if body.get('language', 'auto') not in {'auto', 'en', 'ru', 'uk'}:
                        raise ValueError('Выберите язык: auto, en, ru или uk')
                    source = source_path(Path(value['workspace']), body.get('video'))
                    if any((item := read_json(path, {})).get('status') in {'queued', 'running'}
                           and item.get('video') == str(source)
                           for path in (Path(value['workspace']) / 'output/jobs').glob('*/job.json')):
                        raise ValueError('Эта запись уже находится в обработке')
                    plan = manager.make_plan(body.get('device', manager.settings()['speech_device']))
                    job = enqueue_existing(Path(value['workspace']), body.get('video'), 'whisper-local', body.get('title', ''))
                    job.update(speech_only=True, device_plan=plan, language=body.get('language', 'auto'))
                    write_json(Path(value['workspace']) / 'output/jobs' / job['id'] / 'job.json', job)
                    start_worker(Path(value['workspace']))
                    return self.json_response(202, job)
                except (ValueError, TypeError, OSError, RuntimeError) as exc:
                    return self.json_response(400, {'error': str(exc)})
            if setup is not None and path in {'/api/setup/inspect', '/api/setup/model', '/api/setup/pick-model', '/api/setup/ollama', '/api/setup/download', '/api/setup/probe', '/api/setup/complete', '/api/setup/gemini', '/api/setup/refresh', '/api/setup/component-directory', '/api/setup/storage', '/api/setup/external', '/api/components', '/api/native/postprocess'}:
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    origin = self.headers.get('Origin')
                    if self.headers.get('X-App-Instance') != instance or (origin and urlsplit(origin).netloc != self.headers.get('Host')):
                        if 0 < length <= 4096:
                            self.rfile.read(length)
                        return self.json_response(403, {'error': 'Откройте мастер из приложения'})
                    if path == '/api/setup/probe':
                        if self.headers.get_content_type() == 'application/json' and length == 2:
                            if self.rfile.read(length) != b'{}':
                                raise ValueError('Для встроенного теста ожидается {}')
                            return self.json_response(202, setup.probe())
                        if not 0 < length <= 500000:
                            raise ValueError('Проверочный WAV должен быть не больше 500 КБ и до 15 секунд. Можно запустить встроенный тест.')
                        return self.json_response(202, setup.probe(self.rfile.read(length)))
                    if path == '/api/setup/pick-model':
                        return self.json_response(200, {'path': choose_folder()})
                    if not 0 < length <= (400_000 if path == '/api/native/postprocess' else 4096) or self.headers.get_content_type() != 'application/json':
                        raise ValueError('Ожидается путь к модели в JSON')
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise TypeError('Ожидается объект настроек модели')
                    if path == '/api/setup/storage':
                        action = body.get('action')
                        if action == 'pick':
                            return self.json_response(200, {'path': choose_folder(storage=True)})
                        if action == 'cleanup':
                            if body.get('confirmed') is not True:
                                raise ValueError('Подтвердите очистку старой папки')
                            return self.json_response(200, storage.cleanup())
                        if action != 'transfer':
                            raise ValueError('Неизвестное действие с папкой')
                        return self.json_response(202, storage.start(body))
                    if path == '/api/setup/external':
                        pages = {'ollama-guide': f'http://127.0.0.1:{self.server.server_port}/help/ollama', 'lmstudio-guide': f'http://127.0.0.1:{self.server.server_port}/help/lmstudio', 'terms': 'https://huggingface.co/pyannote/speaker-diarization-community-1', 'tokens': 'https://huggingface.co/settings/tokens'}
                        update = updates.snapshot()
                        if update['update_available']:
                            pages['update-release'] = update['latest']['url']
                        if body.get('page') not in pages:
                            raise ValueError('Неизвестная страница')
                        webbrowser.open(pages[body['page']])
                        return self.json_response(200, {'opened': True})
                    if path == '/api/components':
                        return self.json_response(202, components.action(body.get('component'), body))
                    if path == '/api/setup/component-directory':
                        return self.json_response(200, setup.component_directory(body.get('directory')))
                    if path == '/api/setup/refresh':
                        with manager._lock:
                            setup.guard()
                            manager._inventory = None
                            setup.hardware = None
                            manager.failed.clear()
                        return self.json_response(200, setup.diagnostics())
                    if path == '/api/setup/download':
                        return self.json_response(202, setup.download(body.get('confirmed')))
                    if path == '/api/setup/complete':
                        return self.json_response(200, setup.complete())
                    if path == '/api/setup/gemini':
                        return self.json_response(200, setup.gemini(body))
                    if path == '/api/native/postprocess':
                        setup.guard()
                        if body.get('task') == 'diarize':
                            from video_descriptor.diarization_postprocess import (
                                enqueue as enqueue_diarization,
                            )
                            job = enqueue_diarization(Path(value['workspace']), body.get('folder'), value)
                            start_worker(Path(value['workspace']))
                            return self.json_response(202, job)
                        from video_descriptor.postprocess import enqueue as enqueue_postprocess
                        config = body.get('construction') if body.get('task') == 'notes' else None
                        if config is not None:
                            from video_descriptor.construction import configured, validate_provider
                            config = configured(Path(value['workspace']), {**config, 'input': 'speech'})
                            validate_provider(Path(value['workspace']), config)
                            if config['provider'] == 'gemini' and body.get('cloud_confirmed') is not True:
                                raise ValueError('Подтвердите отправку текста в Google и возможные расходы')
                        from video_descriptor import translation_settings
                        preferences = translation_settings.load(value['workspace'])
                        from video_descriptor.llm_provider import snapshot
                        provider = config['provider'] if config else preferences['provider']
                        route = snapshot(value['workspace'], settings=preferences, provider=provider,
                                         model=config['model'] if config else None,
                                         endpoint=value['ollama_url'] if provider == 'ollama' else None)
                        model = route['model']
                        if provider == 'ollama':
                            validate_ollama_model(value, model)
                        elif provider == 'lmstudio':
                            from video_descriptor.lmstudio import models
                            if model not in {row['id'] for row in models(preferences)}:
                                raise ValueError('Выберите доступную модель LM Studio в настройках')
                        if config is None and body.get('task') == 'notes':
                            from video_descriptor.construction import validate
                            config = validate({'provider': provider, 'model': model})
                        if provider == 'gemini':
                            from video_descriptor.construction import validate_provider
                            validate_provider(Path(value['workspace']), {'provider': provider})
                            if body.get('cloud_confirmed') is not True:
                                raise ValueError('Подтвердите отправку текста в Google и возможные расходы')
                        job = enqueue_postprocess(Path(value['workspace']), body.get('folder'),
                                                  body.get('task'), model, route['endpoint'],
                                                  construction=config, translate_after=body.get('translate_after', True),
                                                  translation_provider=provider)
                        start_worker(Path(value['workspace']))
                        return self.json_response(202, job)
                    if path == '/api/setup/ollama':
                        if 'endpoint' in body:
                            with manager._lock:
                                setup.guard()
                                if components.active:
                                    raise RuntimeError('Дождитесь завершения проверки')
                                return self.json_response(200, components.connect_ollama(body['endpoint']))
                        with manager._lock:
                            return self.json_response(200, select_ollama(value, body.get('model'), body.get('task', 'translation')))
                    result = inspect_model(body.get('path'), HERE) if path.endswith('/inspect') else setup.apply(body.get('path'))
                    return self.json_response(200, result)
                except (ValueError, TypeError, OSError, subprocess.SubprocessError) as exc:
                    return self.json_response(400, {'error': str(exc)})
                except RuntimeError as exc:
                    return self.json_response(409, {'error': str(exc)})
            if path == '/api/upload' and parse_qs(urlsplit(self.path).query).get('engine', [''])[0] != 'whisper-local':
                return super().do_POST()
            if manager is not None and path in {'/api/compute-settings', '/api/native/prepare', '/api/upload'}:
                if self.headers.get('Origin') and urlsplit(self.headers['Origin']).netloc != self.headers.get('Host'):
                    return self.json_response(403, {'error': 'Запрос должен исходить из приложения'})
                try:
                    if path == '/api/compute-settings':
                        length = int(self.headers.get('Content-Length', '0'))
                        if not 0 < length <= 1024 or self.headers.get_content_type() != 'application/json':
                            raise ValueError('Ожидается JSON настроек устройства')
                        return self.json_response(200, manager.save(json.loads(self.rfile.read(length))))
                    if path == '/api/native/prepare':
                        if self.headers.get('X-App-Instance') != instance:
                            return self.json_response(403, {'error': 'Откройте приложение заново'})
                        return self.json_response(202, manager.prepare())
                    params = parse_qs(urlsplit(self.path).query)
                    requested = params.get('device', [manager.settings()['speech_device']])[0]
                    with manager._lock:
                        if manager.operation:
                            raise RuntimeError('Дождитесь завершения настройки')
                        device_plan = manager.make_plan(requested)
                        job = enqueue(Path(value['workspace']), self.rfile, int(self.headers.get('Content-Length', '0')),
                                  params.get('filename', [''])[0], params.get('title', [''])[0],
                                  mode='audio', engine='whisper-local', speech_only=True,
                                  language=params.get('language', ['auto'])[0], device_plan=device_plan)
                    record('job_device_snapshot', job_id=job['id'], requested=device_plan['requested'],
                           device=device_plan['selected'], stage='speech')
                    start_worker(Path(value['workspace']))
                    return self.json_response(202, job)
                except (OSError, RuntimeError, ValueError, TypeError) as exc:
                    return self.json_response(400, {'error': str(exc)})
            if path in {'/api/native/start-npu', '/api/native/stop', '/api/native/cancel'}:
                if self.headers.get('Origin') and urlsplit(self.headers['Origin']).netloc != self.headers.get('Host'):
                    return self.json_response(403, {'error': 'Запрос должен исходить из приложения'})
                if self.headers.get('X-App-Instance') != instance:
                    return self.json_response(403, {'error': 'Откройте приложение заново'})
                try:
                    if path == '/api/native/cancel':
                        from video_descriptor.jobs import request_stop
                        job_id = parse_qs(urlsplit(self.path).query).get('id', [''])[0]
                        return self.json_response(202, request_stop(Path(value['workspace']), job_id))
                    if path.endswith('start-npu'):
                        return self.json_response(202, start_npu(value))
                    if storage and storage.active:
                        return self.json_response(409, {'error': 'Дождитесь завершения переноса данных'})
                    jobs = Path(value['workspace']) / 'output' / 'jobs'
                    # Development reloads only this HTTP process. Queue workers and
                    # device services are independent and keep their own locks.
                    if not value.get('development') and any(read_json(p, {}).get('status') in {'queued', 'running'} for p in jobs.glob('*/job.json')):
                        return self.json_response(409, {'error': 'Дождитесь завершения очереди. Закрытие вкладки не прерывает обработку.'})
                    if components and (components.active or components.plan.get('state') == 'running'):
                        return self.json_response(409, {'error': 'Остановите подготовку компонентов перед закрытием приложения'})
                    if components:
                        components.close()
                    self.json_response(200, {'stopped': True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                except (OSError, ValueError) as exc:
                    return self.json_response(400, {'error': str(exc)})
            return super().do_POST()

        def log_message(self, format, *args):
            LOGGER.info(format, *args)

    return partial(Handler, directory=value['workspace'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--doctor', action='store_true')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--start-npu', action='store_true')
    args = parser.parse_args()
    value = config()
    environment(value)
    if args.doctor:
        print(json.dumps(doctor(value), ensure_ascii=False, indent=2))
        return 0
    url = f'http://127.0.0.1:{value["port"]}'
    fingerprint = installation_id()[:16]
    state = HERE / 'runtime' / f'instance-{fingerprint}.json'
    if args.stop:
        recorded = json.loads(state.read_text(encoding='utf-8'))
        info = fetch(url + '/health')
        if info.get('app') != APP or info.get('instance') != recorded['instance'] or info.get('workspace') != value['workspace']:
            raise ValueError('На порту другой экземпляр; остановка отменена')
        request = urllib.request.Request(url + '/api/native/stop', data=b'',
                                         headers={'X-App-Instance': recorded['instance']}, method='POST')
        with urllib.request.urlopen(request, timeout=5) as response:
            print(response.read().decode())
        return 0
    state.parent.mkdir(parents=True, exist_ok=True)
    logs = HERE / 'runtime' / 'logs'
    logs.mkdir(exist_ok=True)
    logging.basicConfig(filename=logs / 'app.log', encoding='utf-8', level=logging.INFO)
    from video_descriptor.platform_support import lock_file
    with (state.parent / f'instance-{fingerprint}.lock').open('a+') as lock:
        try:
            lock_file(lock)
        except BlockingIOError:
            for _ in range(30):
                try:
                    info = fetch(url + '/health')
                    if info.get('app') != APP or info.get('workspace') != value['workspace']:
                        raise ValueError('Порт занят другим приложением')
                    if not args.no_browser:
                        webbrowser.open(url)
                    print('Уже запущено: ' + url)
                    return 0
                except (OSError, urllib.error.URLError):
                    time.sleep(.2)
            raise ValueError('Другой экземпляр запускается, но не ответил за 6 секунд; см. runtime/logs/app.log') from None
        workspace = Path(value['workspace'])
        for folder in ('data', 'output', '.devcontainer'):
            (workspace / folder).mkdir(parents=True, exist_ok=True)
        # Recover abandoned statuses without restarting the old queue.
        from video_descriptor.jobs import recover_interrupted
        recover_interrupted(workspace)
        if args.start_npu:
            print(json.dumps(start_npu(value)))
        instance = uuid.uuid4().hex
        from updates import UpdateChecker
        updates = UpdateChecker(VERSION, BUILD, Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'VideoDescriptor/update-cache.json',
                                supported=not value.get('development', False))
        with NativeHTTPServer(('127.0.0.1', value['port']), make_handler(value, instance, updates)) as server:
            state.write_text(json.dumps({'instance': instance, 'pid': os.getpid(), 'workspace': value['workspace']}), encoding='utf-8')
            print('Готово: ' + url, flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            try:
                updates.start()
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                updates.close()
                state.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print('Не удалось запустить приложение: ' + str(exc), file=sys.stderr)
        raise SystemExit(1) from None
