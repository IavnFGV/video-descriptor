"""Isolated UI preview with fixture APIs. Never starts services or writes user data.

python scripts/preview-ui.py --port 8948
Open /?preview=ready or setup/queued/running/error/done/no-speech/offline/upload-error.
The real desktop HTML/CSS/JS is used unchanged; only this server injects a banner.
"""
import argparse
import io
import json
import socket
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = {'ready', 'setup', 'queued', 'running', 'error', 'done', 'no-speech', 'offline', 'upload-error'}


class Preview(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, value, status=200, mime='application/json'):
        body = json.dumps(value, ensure_ascii=False).encode() if mime == 'application/json' else value
        self.send_response(status)
        self.send_header('Content-Type', mime + ('; charset=utf-8' if mime.startswith('text/') else ''))
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def fixture_job(self):
        state = self.server.scenario
        return {'id': 'fixture-job', 'folder': 'fixture', 'filename': 'example.wav',
                'title': 'Интервью о новом проекте · пример', 'created': 1,
                'mode': 'audio', 'status': state if state in {'queued', 'running', 'error'} else 'done',
                'error': 'Обработчик недоступен. Проверьте компоненты и продолжите из кэша.' if state == 'error' else '',
                'device_plan': {'requested': 'AUTO', 'selected': 'NPU'}}

    def do_GET(self):
        url = urlsplit(self.path)
        path, query = url.path, parse_qs(url.query)
        if path == '/':
            state = query.get('preview', ['ready'])[0]
            self.server.scenario = state if state in SCENARIOS else 'ready'
            page = (ROOT / 'windows-app/ui/index.html').read_text(encoding='utf-8')
            page = page.replace('<body>', '<body><p role="note" style="margin:0;padding:8px;text-align:center;background:#fff4d6;color:#795000">Предпросмотр UI · все API и данные демонстрационные · AI не запускается</p>')
            return self.reply(page.encode(), mime='text/html')
        assets = {'/native.js': 'windows-app/ui/app.js', '/native.css': 'windows-app/ui/app.css',
                  '/studio-assets/speech-edit.js': 'video_descriptor/assets/speech-edit.js'}
        if path in assets:
            return self.reply((ROOT / assets[path]).read_bytes(), mime='text/css' if path.endswith('.css') else 'text/javascript')
        if path == '/fixture.wav':
            data = io.BytesIO()
            with wave.open(data, 'wb') as wav:
                wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                wav.writeframes(b'\0\0' * 32000)
            return self.reply(data.getvalue(), mime='audio/wav')
        if path == '/__preview/requests':
            return self.reply(self.server.requests)
        if path == '/health':
            return self.reply({'instance': 'preview-instance'})
        state = self.server.scenario
        if path == '/api/doctor':
            if state == 'offline':
                return self.reply({'error': 'Fixture: соединение недоступно'}, 503)
            ready = state != 'setup'
            return self.reply({'ffmpeg': True, 'ollama': {'ready': False}, 'compute': {
                'selected': 'NPU', 'settings': {'speech_device': self.server.device},
                'preparing': False, 'operation': None, 'error': '',
                'capabilities': {name: {'available': True, 'ready': ready and name == 'NPU',
                                       'reason': 'Модель готова' if ready and name == 'NPU' else 'Нужна подготовка'}
                                 for name in ('NPU', 'GPU', 'CPU')}}})
        if path == '/api/setup':
            return self.reply({'completed': state != 'setup', 'model_present': True,
                               'model_path': 'D:\\AI\\models\\whisper-small', 'verified': True,
                               'download': {'source': 'Fixture source', 'revision': 'preview', 'download_bytes': 500000000},
                               'operation': {'status': 'idle', 'message': '', 'bytes': 0, 'total': 0}})
        if path == '/api/setup/ollama':
            return self.reply({'models': [{'name': 'preview-model', 'bytes': 1024 ** 3}],
                               'selected': 'preview-model', 'ready': False, 'message': 'Демонстрационное подключение'})
        if path == '/api/setup/diagnostics':
            return self.reply({'hardware': {'cpu': 'Preview CPU', 'intel_gpu': ['Preview GPU'], 'intel_npu': ['Preview NPU']},
                               'inventory': {'openvino': 'preview', 'genai': 'preview', 'devices': ['NPU', 'GPU', 'CPU']},
                               'translation': {'state': 'unconfigured'}, 'notes': {'state': 'unconfigured', 'selected': ''},
                               'ocr': {'message': 'Не настроен'}, 'diarization': {'message': 'Не подготовлена'},
                               'gemini': {'model': 'preview-model', 'billing_mode': 'paid', 'free_ack': False, 'has_key': False}})
        if path == '/api/native/events':
            return self.reply([])
        if path == '/api/jobs':
            return self.reply([] if state in {'ready', 'setup', 'offline', 'upload-error'} else [self.fixture_job()])
        if path == '/api/speech':
            job = self.fixture_job()
            result = None if state == 'queued' else {
                'folder': 'fixture', 'video': 'fixture.wav', 'device': 'NPU', 'duration': 10, 'processed': 4,
                'status': 'done' if job['status'] == 'done' else 'running', 'edit_revision': 0,
                'has_translation': False, 'no_speech': state == 'no-speech',
                'segments': [] if state == 'no-speech' else [
                    {'id': 's1', 'start': 0, 'end': 1, 'text': 'Это пример расшифровки для проверки интерфейса.', 'speaker': 'S1'},
                    {'id': 's2', 'start': 1, 'end': -1, 'text': 'Конечная метка не определена.', 'speaker': 'S1'}]}
            return self.reply({'job': job, 'result': result})
        if path in {'/api/subtitles', '/api/transcript-text'}:
            return self.reply(b'Fixture export only', mime='text/plain')
        if path == '/favicon.ico':
            return self.reply(b'', 204, 'image/x-icon')
        return self.reply({'error': 'Preview route not implemented'}, 404)

    def do_POST(self):
        url = urlsplit(self.path)
        size = int(self.headers.get('Content-Length', '0'))
        if size > 2_000_000:
            self.close_connection = True
            return self.reply({'error': 'Preview принимает только тестовые файлы до 2 МБ'}, 413)
        # Fixture previews must not retain media or credentials.
        raw = self.rfile.read(size)
        payload = None
        if 'application/json' in self.headers.get('Content-Type', ''):
            payload = json.loads(raw or b'{}')
            if 'api_key' in payload:
                payload['api_key'] = '[redacted]'
        self.server.requests.append({'path': url.path, 'query': parse_qs(url.query),
                                     'instance': self.headers.get('X-App-Instance'),
                                     'content_type': self.headers.get('Content-Type'), 'bytes': size, 'json': payload})
        if url.path == '/api/upload':
            if self.server.scenario == 'upload-error':
                self.server.scenario = 'offline'
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.server.scenario = 'queued'
            return self.reply({'id': 'fixture-job'}, 202)
        if url.path in {'/api/retry', '/api/native/postprocess'}:
            self.server.scenario = 'running'
            return self.reply({'id': 'fixture-job'})
        if url.path == '/api/compute-settings':
            self.server.device = payload['speech_device']
            return self.reply({'speech_device': self.server.device})
        if url.path == '/api/setup/pick-model':
            return self.reply({'path': ''})
        if url.path in {'/api/setup/inspect', '/api/setup/model'}:
            return self.reply({'model': 'Preview Whisper', 'bytes': 500000000})
        if url.path == '/api/setup/ollama':
            return self.reply({'selected': payload['model']})
        if url.path == '/api/setup/gemini':
            return self.reply({'models': [], 'message': 'Fixture only', 'available': False})
        if url.path in {'/api/setup/complete', '/api/setup/refresh', '/api/setup/probe', '/api/setup/download', '/api/native/prepare'}:
            return self.reply({'status': 'done'})
        if url.path == '/api/native/stop':
            return self.reply({'error': 'Fixture: активное задание, остановка запрещена'}, 409)
        return self.reply({'error': 'Preview mutation not implemented'}, 404)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8948)
    args = parser.parse_args()
    with ThreadingHTTPServer(('127.0.0.1', args.port), Preview) as server:
        server.scenario, server.device, server.requests = 'ready', 'AUTO', []
        print(f'Fixture UI only: http://127.0.0.1:{args.port}/?preview=ready', flush=True)
        server.serve_forever()
