"""Disposable loopback Ollama protocol fixture. Never a production inference backend."""
import hashlib
import json
import re
import threading
from contextlib import AbstractContextManager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = 'acceptance-fixture:1'
NOTES = '## Оглавление\n### [{stamp}] Проверка записи\nЛокальная обработка записи.\n\n## Конспект\n### [{stamp}] Проверка записи\nТестовая запись обработана локально; результат можно сохранить как субтитры.\n'


class LLMFixture(AbstractContextManager):
    def __init__(self):
        self.events = []
        self.mode = 'valid'
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # No prompts/transcripts in common or console logs.

            def reply(self, value, status=200):
                data = json.dumps(value, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                fixture.events.append({'route': self.path, 'method': 'GET'})
                if self.path == '/api/version':
                    return self.reply({'version': '0.0.0-acceptance-fixture'})
                if self.path == '/api/tags':
                    return self.reply({'models': [{'name': MODEL, 'model': MODEL, 'size': 0,
                        'digest': hashlib.sha256(MODEL.encode()).hexdigest()}]})
                self.reply({'error': 'Unsupported fixture route'}, 404)

            def do_POST(self):
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    if not 0 < length <= 2_000_000:
                        raise ValueError('Invalid fixture request length')
                    body = json.loads(self.rfile.read(length))
                    if body.get('model') != MODEL:
                        raise ValueError('Unexpected fixture model')
                    event = {'route': self.path, 'method': 'POST', 'mode': fixture.mode}
                    fixture.events.append(event)
                    if self.path == '/api/show':
                        return self.reply({'capabilities': ['completion'],
                            'model_info': {'fixture.context_length': 16384}, 'parameters': ''})
                    if self.path == '/api/generate':
                        return self.reply({'model': MODEL, 'response': 'ready', 'done': True})
                    if self.path != '/api/chat':
                        return self.reply({'error': 'Unsupported fixture route'}, 404)
                    messages = body['messages']
                    if [row['role'] for row in messages] != ['system', 'user'] or body.get('stream') is not True:
                        raise ValueError('Expected real system/user streaming chat protocol')
                    text = messages[1]['content']
                    markers = re.findall(r'\[\[s\d+\]\]', text)
                    if markers:
                        event['task'] = 'translation'
                        answer = '\n\n'.join(marker + '\nТестовая запись обработана локально.' for marker in markers)
                    elif 'самостоятельную статью' in messages[0]['content']:
                        event['task'] = 'article'
                        answer = '# Локальная обработка записи\n\nТестовая запись обработана локально. Результат можно сохранить как субтитры.\n'
                    else:
                        event['task'] = 'notes'
                        stamps = re.findall(r'\[(\d{2,}:[0-5]\d:[0-5]\d)\]', text)
                        if not stamps:
                            raise ValueError('Expected source timestamps for notes')
                        answer = NOTES.format(stamp=stamps[0])
                    if fixture.mode == 'invalid-notes':
                        answer = 'Invalid model response without required headings.'
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/x-ndjson')
                    self.end_headers()
                    # Deliberately split protocol messages and content across streamed chunks.
                    chunks = [answer[:len(answer)//2], answer[len(answer)//2:]]
                    for chunk in chunks:
                        self.wfile.write((json.dumps({'message': {'content': chunk}, 'done': False}, ensure_ascii=False) + '\n').encode())
                        self.wfile.flush()
                    if fixture.mode != 'truncated':
                        self.wfile.write(b'{"message":{"content":""},"done":true,"done_reason":"stop"}\n')
                        self.wfile.flush()
                except (ValueError, KeyError, TypeError) as error:
                    self.reply({'error': str(error)}, 400)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def evidence(self):
        return {'method': 'mocked LLM HTTP boundary; no real LLM inference claim',
                'model': MODEL, 'events': list(self.events)}
