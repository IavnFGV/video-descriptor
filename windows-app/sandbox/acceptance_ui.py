"""Guest-only WebView2 acceptance driver. Mutating product actions use DOM input.

CDP is enabled only on loopback in the disposable guest. HTTP requests below are
read-only evidence collection, except the explicitly labelled inference diagnostic.
No Playwright/browser/Python installation is required: use the packaged Python.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

# The packaged Python uses an isolated _pth and omits the script directory.
# Include the staged driver directory so shared workspace checks load in Sandbox.
sys.path.insert(0, str(Path(__file__).resolve().parent))


class Blocked(RuntimeError):
    pass


def read_http(url, *, data=None, timeout=30):
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(),
                                 headers={'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as response:
        return response.read()


def wait_for(read, predicate=bool, timeout=120):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            value = read()
            if predicate(value):
                return value
        except (OSError, ValueError, KeyError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise TimeoutError(f'Condition timed out after {timeout}s; last error: {last_error}')


class CDP:
    """Small synchronous RFC6455 client for trusted, loopback-only DevTools."""

    def __init__(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != 'ws' or parsed.hostname != '127.0.0.1':
            raise ValueError('Only loopback DevTools is allowed')
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=30)
        self.sequence = 0
        key = base64.b64encode(os.urandom(16)).decode()
        header = (f'GET {parsed.path} HTTP/1.1\r\nHost: 127.0.0.1:{parsed.port}\r\n'
                  f'Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n'
                  'Sec-WebSocket-Version: 13\r\n\r\n')
        self.sock.sendall(header.encode())
        response = bytearray()
        while not response.endswith(b'\r\n\r\n'):
            response.extend(self.exact(1))
            if len(response) > 65536:
                raise ValueError('Oversized WebSocket handshake')
        expected = base64.b64encode(hashlib.sha1(
            (key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
        if b' 101 ' not in response.split(b'\r\n')[0] or expected.lower() not in response.lower():
            raise ConnectionError('Invalid WebSocket upgrade response')

    def exact(self, count):
        data = bytearray()
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise ConnectionError('DevTools socket closed')
            data.extend(chunk)
        return bytes(data)

    def send(self, payload, opcode=1):
        mask = os.urandom(4)
        size = len(payload)
        prefix = bytes([0x80 | opcode])
        if size < 126:
            prefix += bytes([0x80 | size])
        elif size < 65536:
            prefix += b'\xfe' + struct.pack('!H', size)
        else:
            prefix += b'\xff' + struct.pack('!Q', size)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.sock.sendall(prefix + mask + masked)

    def receive(self):
        assembled = bytearray()
        while True:
            first, second = self.exact(2)
            length = second & 127
            if length == 126:
                length = struct.unpack('!H', self.exact(2))[0]
            elif length == 127:
                length = struct.unpack('!Q', self.exact(8))[0]
            if length > 32 * 1024 * 1024 or second & 128:
                raise ValueError('Invalid DevTools frame')
            payload = self.exact(length)
            opcode = first & 15
            if opcode == 8:
                raise ConnectionError('DevTools closed WebSocket')
            if opcode == 9:
                self.send(payload, opcode=10)
                continue
            if opcode == 10:
                continue
            assembled.extend(payload)
            if first & 128:
                return json.loads(assembled)

    def call(self, method, **params):
        self.sequence += 1
        ident = self.sequence
        self.send(json.dumps({'id': ident, 'method': method, 'params': params}).encode())
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            message = self.receive()
            if message.get('id') == ident:
                if 'error' in message:
                    raise RuntimeError(f'{method}: {message["error"]}')
                return message.get('result', {})
        raise TimeoutError(f'No response to {method}')

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', expression=expression, returnByValue=True,
                           awaitPromise=True)
        if 'exceptionDetails' in result:
            raise RuntimeError(str(result['exceptionDetails']))
        return result.get('result', {}).get('value')

    def click(self, selector):
        # Dispatch real pointer input; never invoke product handlers or fetch mutations.
        quoted = json.dumps(selector)
        point = self.evaluate(f'''(() => {{const e=document.querySelector({quoted});
            if(!e || e.disabled || e.hidden) return null;
            e.scrollIntoView({{block:'center',behavior:'instant'}});
            const r=e.getBoundingClientRect();return r.width&&r.height?[r.x+r.width/2,r.y+r.height/2]:null;}})()''')
        if not point:
            raise RuntimeError(f'UI control unavailable: {selector}')
        for action in ('mousePressed', 'mouseReleased'):
            self.call('Input.dispatchMouseEvent', type=action, x=point[0], y=point[1],
                      button='left', clickCount=1)

    def fill(self, selector, value):
        self.evaluate(f'''(() => {{const e=document.querySelector({json.dumps(selector)});
            if(!e) throw Error('Missing input'); e.value={json.dumps(value)};
            e.dispatchEvent(new Event('input',{{bubbles:true}}));
            e.dispatchEvent(new Event('change',{{bubbles:true}}));}})()''')

    def visible_text(self, selector):
        return self.evaluate(f'document.querySelector({json.dumps(selector)})?.textContent || ""')

    def screenshot(self, target):
        image = self.call('Page.captureScreenshot', format='png')
        target.write_bytes(base64.b64decode(image['data']))


def attach():
    targets = json.loads(read_http('http://127.0.0.1:9222/json/list'))
    for target in targets:
        parsed = urlsplit(target.get('url', ''))
        if (target.get('type') == 'page' and parsed.scheme == 'http'
                and parsed.hostname == '127.0.0.1'):
            return CDP(target['webSocketDebuggerUrl'])
    return None


def run(args, evidence):
    cdp = wait_for(attach, timeout=150)
    try:
        wait_for(lambda: cdp.evaluate('!!document.querySelector("#setup-open")'))
        origin = cdp.evaluate('location.origin')

        def api(path):
            return json.loads(read_http(origin + path))

        def save(name, value):
            (args.reports / name).write_text(json.dumps(value, ensure_ascii=False, indent=2),
                                             encoding='utf-8')

        def connect_model(task):
            cdp.click('#setup-open')
            cdp.click('#ollama-refresh')
            wait_for(lambda: cdp.evaluate(
                f'[...document.querySelector("#ollama-model").options].some(o=>o.value==={json.dumps(args.model)})'))
            cdp.fill('#ollama-model', args.model)
            cdp.fill('#ollama-task', task)
            cdp.click('#ollama-connect')
            wait_for(lambda: next(row for row in api('/api/components')['components'] if row['id'] == 'ollama'),
                     lambda row: row['state'] == 'ready' and row.get('proof', {}).get('model') == args.model
                     and row.get('proof', {}).get('task') == task, timeout=240)

        def completed():
            value = cdp.visible_text('#status')
            if value == 'Нужна проверка':
                raise RuntimeError(cdp.visible_text('#progress-text'))
            return value == 'Готово'

        stage = args.stage
        evidence['method'] = 'real installed WinForms/WebView2 DOM and pointer input'
        evidence['app_version'] = api('/health').get('version')
        if stage == 'desktop':
            if not cdp.evaluate('document.querySelector("#setup-wizard").hidden'):
                raise RuntimeError('First-run wizard unexpectedly blocks the main screen')
            wait_for(lambda:cdp.visible_text('#bootstrap-message'),lambda text:text and 'Проверяем' not in text)
            cdp.screenshot(args.reports / 'zero-config-first-launch.png')
            cdp.click('#setup-open')
            if cdp.evaluate('[...document.querySelectorAll(".ai-section")].some(e=>e.open)'):
                raise RuntimeError('Technical settings are expanded by default')
            wait_for(lambda:cdp.visible_text('#ai-summary'),lambda text:text and 'Проверяем' not in text)
            if 'Failed to fetch' in cdp.visible_text('body'):
                raise RuntimeError('Raw startup fetch error leaked into UI')
            cdp.screenshot(args.reports / 'zero-config-settings.png')
            wait_for(lambda: cdp.visible_text('#setup-diagnostics'),
                     lambda text: 'OpenVINO' in text and 'CPU' in text)
            evidence['diagnostics'] = api('/api/setup/diagnostics')
            evidence['wizard_open'] = not cdp.evaluate('document.querySelector("#setup-wizard").hidden')
            if not evidence['wizard_open']:
                raise RuntimeError('Setup wizard did not open')
        elif stage == 'whisper':
            plan = json.loads(Path('C:/VD-Acceptance/plan.json').read_text(encoding='utf-8-sig'))
            if plan['network_download']:
                cdp.click('#new-record-open')
                document = cdp.call('DOM.getDocument')['root']['nodeId']
                node = cdp.call('DOM.querySelector', nodeId=document, selector='#file')['nodeId']
                cdp.call('DOM.setFileInputFiles', nodeId=node, files=[str(args.root / 'windows-app/samples/speech-check.mp4')])
                wait_for(lambda:not cdp.evaluate('document.querySelector("#prepare-speech").hidden'))
                cdp.call('Page.enable')
                cdp.click('#prepare-speech')
                wait_for(lambda:cdp.evaluate('document.querySelector("#speech-download-dialog").open'))
                cdp.click('#speech-download-cancel')
                assert api('/api/components')['active'] is None
                assert cdp.evaluate('document.querySelector("#file").files[0]?.name') == 'speech-check.mp4'
                evidence['download_refusal_preserved_file_and_started_nothing'] = True
                cdp.click('#prepare-speech')
                wait_for(lambda:cdp.evaluate('document.querySelector("#speech-download-dialog").open'))
                cdp.click('#speech-download-confirm')
                operation = wait_for(lambda: next(row for row in api('/api/components')['components'] if row['id'] == 'whisper'),
                                     lambda op: op['state'] in {'ready', 'error'}, timeout=900)
                if operation['state'] != 'ready':
                    raise RuntimeError(f'Whisper network download failed: {operation}')
                assert cdp.evaluate('document.querySelector("#file").files[0]?.name') == 'speech-check.mp4'
                evidence['selected_file_preserved'] = True
                evidence['download_confirmations'] = 1
            else:
                cdp.click('#setup-open')
                cdp.click('#setup-card > summary')
                objects = [obj for obj in plan['cache'] if obj['component'] == 'whisper-model']
                if not objects:
                    raise Blocked('No verified whisper-model cache. Register official test assets or use -NetworkDownload.')
                model_path = 'C:\\VD-Cache\\' + objects[0]['id']
                if objects[0].get('payload'):
                    model_path += '\\' + objects[0]['payload']
                if cdp.evaluate('document.querySelector("#setup-form").hidden'):
                    cdp.click('#setup-toggle')
                cdp.fill('#model-path', model_path)
                cdp.click('#apply-model')
                wait_for(lambda: cdp.visible_text('#setup-feedback'), lambda text: 'Модель подключена' in text)
                wait_for(lambda: not api('/api/compute-settings')['preparing'])
                cdp.fill('#speech-device', 'CPU')
                wait_for(lambda: api('/api/compute-settings')['settings']['speech_device'] == 'CPU')
                compute = wait_for(lambda: api('/api/compute-settings'),
                                   lambda state: not state['preparing'] and state['capabilities']['CPU']['ready'], timeout=240)
                evidence['compute'] = compute
                cdp.click('.ai-section:last-of-type > summary')
                cdp.click('#setup-finish')
                cdp.click('#new-record-open')
                document = cdp.call('DOM.getDocument')['root']['nodeId']
                node = cdp.call('DOM.querySelector', nodeId=document, selector='#file')['nodeId']
                cdp.call('DOM.setFileInputFiles', nodeId=node, files=[str(args.root / 'windows-app/samples/speech-check.mp4')])
            cdp.fill('#language', 'en')
            wait_for(lambda: not cdp.evaluate('document.querySelector("#start").disabled'))
            cdp.click('#start')
            wait_for(completed, timeout=240)
            source_job = cdp.evaluate('new URLSearchParams(location.search).get("job")')
            speech = api('/api/speech?job=' + source_job)
            if not speech.get('result', {}).get('segments'):
                raise RuntimeError('Video produced no actual speech segments')
            result = speech['result']
            if result.get('device') != 'CPU':
                raise RuntimeError('Explicit CPU selection was not respected')
            for segment in result['segments']:
                if not (0 <= segment['start'] <= segment['end'] <= result['duration'] + 0.1):
                    raise RuntimeError('Transcription contains invalid timestamps')
            evidence['video'] = speech
            cdp.click('#diarize-run')
            wait_for(lambda: cdp.evaluate('document.querySelector("#speaker-dialog").open'))
            cdp.screenshot(args.reports / 'zero-config-speaker-choice.png')
            cdp.click('#speaker-go')
            wait_for(lambda:not cdp.evaluate('document.querySelector("#speaker-go").disabled'))
            assert api('/api/components')['active'] is None
            evidence['speaker_without_consent_starts_nothing'] = True
            cdp.call('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
            cdp.call('Input.dispatchKeyEvent', type='keyUp', key='Escape', code='Escape', windowsVirtualKeyCode=27)
            evidence['speaker_choice_from_record'] = True
            evidence['speaker_choice_did_not_modify_record'] = api('/api/speech?job=' + source_job)['result']['segments'] == result['segments']
            save('workflow-state.json', {'source_job': source_job})
        elif stage == 'ollama-install':
            version = wait_for(lambda: json.loads(read_http('http://127.0.0.1:11434/api/version')))
            cdp.click('#setup-open')
            cdp.click('#ollama-refresh')
            evidence['ollama_version'] = version
            evidence['preparation_method'] = 'signed official installer in disposable guest; UI state checked separately'
            evidence['ui_feedback'] = wait_for(lambda: cdp.visible_text('#ollama-feedback'))
        elif stage == 'ollama-model':
            connect_model('translation')
            evidence['ui_feedback'] = cdp.visible_text('#ollama-feedback')
            tags = json.loads(read_http('http://127.0.0.1:11434/api/tags'))
            selected = [model for model in tags['models'] if model['name'] == args.model]
            if not selected or not selected[0].get('digest'):
                raise RuntimeError('Selected model is absent or has no digest')
            evidence['installed_model'] = selected[0]
            save('ollama-model-identity.json', selected[0])
        elif stage == 'ollama-inference':
            evidence['method'] = 'diagnostic Ollama HTTP API; does not claim UI generation test'
            started = time.monotonic()
            response = json.loads(read_http('http://127.0.0.1:11434/api/generate', data={
                'model': args.model, 'prompt': 'Reply with one short sentence about a train arriving at nine.',
                'stream': False, 'options': {'temperature': 0, 'num_predict': 96}}, timeout=300))
            if not response.get('response', '').strip() or not response.get('done'):
                raise RuntimeError('Ollama generated no completed response')
            evidence.update(response=response, seconds=time.monotonic() - started)
        elif stage in {'translation', 'notes'}:
            state = json.loads((args.reports / 'workflow-state.json').read_text())
            cdp.call('Page.navigate', url=origin + '/?job=' + state['source_job'])
            wait_for(lambda: cdp.evaluate('!!document.querySelector("#setup-open")'))
            wait_for(completed)
            connect_model('translation' if stage == 'translation' else 'notes')
            cdp.click('#setup-finish')
            cdp.click('#translate-run' if stage == 'translation' else '#notes-run')
            wait_for(lambda: cdp.evaluate('new URLSearchParams(location.search).get("job")'),
                     lambda value: value and value != state['source_job'])
            wait_for(completed, timeout=600)
            job = cdp.evaluate('new URLSearchParams(location.search).get("job")')
            speech = api('/api/speech?job=' + job)
            folder = args.root / 'windows-app/runtime/workspace/output' / speech['job']['folder']
            if not folder.resolve().is_relative_to((args.root / 'windows-app/runtime/workspace/output').resolve()):
                raise ValueError('Result folder escaped workspace')
            translations = json.loads((folder / 'translations.json').read_text(encoding='utf-8'))
            transcript = json.loads((folder / 'transcript.json').read_text(encoding='utf-8'))
            if not transcript or not all(str(translations.get(row['id'], '')).strip() for row in transcript):
                raise RuntimeError('Saved translation is empty')
            if any('\u0400' <= char <= '\u04ff' for char in ''.join(translations.values())) is False:
                raise RuntimeError('Russian translation contains no Cyrillic text')
            if (folder / 'translation-errors.json').exists() and json.loads((folder / 'translation-errors.json').read_text()):
                raise RuntimeError('Saved translation has errors')
            evidence['result'] = speech
            evidence['saved_translations'] = translations
            downloads = args.reports / ('downloads-' + stage)
            downloads.mkdir(exist_ok=True)
            cdp.call('Browser.setDownloadBehavior', behavior='allow', downloadPath=str(downloads))
            cdp.click('#ru-srt')
            exported = wait_for(lambda: list(downloads.glob('*.srt')),
                                lambda files: len(files) == 1 and files[0].stat().st_size > 0)
            subtitle = exported[0].read_text(encoding='utf-8-sig')
            if '-->' not in subtitle:
                raise RuntimeError('Translated SRT has no timestamps')
            (args.reports / 'translated.srt').write_text(subtitle, encoding='utf-8')
            if stage == 'notes':
                notes = json.loads((folder / 'notes.json').read_text(encoding='utf-8'))
                if not notes.get('notes'):
                    raise RuntimeError('Saved notes are empty')
                evidence['saved_notes'] = notes
                (args.reports / 'notes-report.html').write_bytes((folder / 'report.html').read_bytes())
        else:
            raise ValueError(f'Unknown UI stage: {stage}')
        if stage in {'whisper', 'notes'}:
            from verify_workspace_ui import run as verify_workspace

            source_folder = speech['job']['folder'] if stage == 'whisper' else api(
                '/api/speech?job=' + state['source_job'])['job']['folder']
            workspace_reports = args.reports / ('workspace-' + stage)
            workspace_reports.mkdir(exist_ok=True)
            workspace_result = {'status': 'FAIL', 'checks': [], 'screens': []}
            try:
                verify_workspace(argparse.Namespace(base=origin, debug_port=9222, target_id=None,
                    folder=source_folder, notes_folder=speech['job']['folder'] if stage == 'notes' else None,
                    output=workspace_reports, edit_reply=stage == 'whisper'), workspace_result)
                workspace_result['status'] = 'PASS'
            finally:
                (workspace_reports / 'workspace-ui.json').write_text(
                    json.dumps(workspace_result, ensure_ascii=False, indent=2), encoding='utf-8')
            evidence['workspace_ui'] = workspace_result['checks']
            cdp.call('Page.navigate', url=origin + '/?job=' + (source_job if stage == 'whisper' else job))
            wait_for(lambda: cdp.evaluate('!!document.querySelector("#setup-open")'))
        cdp.screenshot(args.reports / (stage + '.png'))
    except Exception:
        try:
            cdp.screenshot(args.reports / (args.stage + '-failure.png'))
            (args.reports / (args.stage + '-failure.txt')).write_text(
                cdp.evaluate('document.body.innerText'), encoding='utf-8')
        except (OSError, RuntimeError, ValueError):
            pass
        raise
    finally:
        cdp.sock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--reports', type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--reuse-expensive-proof', action='store_true')
    args = parser.parse_args()
    if os.name != 'nt' or os.environ.get('USERNAME', '').lower() != 'wdagutilityaccount':
        raise SystemExit('Guest-only driver refused host execution')
    evidence = {'stage': args.stage, 'status': 'FAIL'}
    started = time.monotonic()
    try:
        run(args, evidence)
        evidence['status'] = 'PASS'
    except Blocked as exc:
        evidence.update(status='BLOCKED', reason=str(exc))
    except Exception as exc:  # noqa: BLE001 -- test runner must persist unexpected failures
        evidence.update(status='FAIL', reason=f'{type(exc).__name__}: {exc}')
    evidence['elapsed_seconds'] = round(time.monotonic() - started, 3)
    target = args.reports / (args.stage + '.json')
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'stage': args.stage, 'status': evidence['status']}))
    # Parent reads the structured status even for BLOCKED/FAIL; missing result is a failure.


if __name__ == '__main__':
    main()
