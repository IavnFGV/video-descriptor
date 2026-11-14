"""Offline Edge/CDP check of the real native update markup, CSS and JS."""
import json
import socket
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'windows-app/sandbox'))
from acceptance_ui import CDP, read_http, wait_for


def main():
    state = {'installed': {'version': '0.9.3', 'build': 7}, 'latest': None,
             'status': 'ok', 'update_available': False}
    calls = []
    health_calls = []
    health_mode = {'value': 'windows'}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/health':
                health_calls.append(self.path)
                if health_mode['value'] == 'unavailable':
                    self.send_error(503)
                    return
                health = {'app': 'video-descriptor-windows', 'instance': 'test-instance', 'version': '0.9.3', 'build': 7}
                body, kind = json.dumps(health if health_mode['value'] == 'windows' else {'status': 'ok'}).encode(), 'application/json'
            elif self.path == '/api/updates':
                body, kind = json.dumps(state).encode(), 'application/json'
            elif self.path.split('?')[0] in {'/create', '/output/', '/help/ollama', '/help/lmstudio'}:
                body = ('<!doctype html><html><meta charset="utf-8"><link rel="stylesheet" href="/native.css">'
                        '<script src="/studio-assets/desktop-shell.js"></script><body>'
                        '<nav class="vd-global-nav"><a href="/output/">Записи</a></nav>'
                        '<main>Isolated shared shell fixture</main></body></html>').encode()
                kind = 'text/html'
            elif self.path == '/studio-assets/desktop-shell.js':
                body, kind = (ROOT / 'video_descriptor/assets/desktop-shell.js').read_bytes(), 'text/javascript'
            else:
                name = {'/': 'index.html', '/native.css': 'app.css', '/updates.js': 'updates.js'}.get(self.path)
                if not name:
                    self.send_error(404)
                    return
                text = (ROOT / 'windows-app/ui' / name).read_text(encoding='utf-8')
                # Exercise the isolated update component, not unrelated model setup.
                if name == 'index.html':
                    text = text.replace('<script src="/native.js">', '<script type="text/plain">')
                    text = text.replace('<script src="/studio-assets/speech-edit.js">', '<script type="text/plain">')
                body = text.encode()
                kind = {'html': 'text/html', 'css': 'text/css', 'js': 'text/javascript'}[name.rsplit('.', 1)[1]]
            self.send_response(200)
            self.send_header('Content-Type', kind+'; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            calls.append((self.path, self.rfile.read(int(self.headers.get('Content-Length', 0))).decode()))
            if self.path == '/api/native/stop':
                assert self.headers.get('X-App-Instance') == 'test-instance'
                self.send_response(409)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Active fixture job prevents shutdown'}).encode())
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(state).encode())

        def log_message(self, *args):
            pass

    with tempfile.TemporaryDirectory(prefix='vd-updates-ui-') as temporary, ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            debug = probe.getsockname()[1]
        edge = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
        child = subprocess.Popen([edge, '--headless=new', '--disable-gpu', '--no-first-run',
                                  f'--user-data-dir={temporary}/edge', f'--remote-debugging-port={debug}', 'about:blank'],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        browser = psutil.Process(child.pid)
        try:
            tabs = wait_for(lambda: json.loads(read_http(f'http://127.0.0.1:{debug}/json/list')), timeout=30)
            c = CDP(next(tab for tab in tabs if tab.get('type') == 'page')['webSocketDebuggerUrl'])
            c.call('Page.enable')
            c.call('Page.navigate', url=f'http://127.0.0.1:{server.server_port}/')
            wait_for(lambda: c.evaluate('!!window.updatesUI'))
            c.evaluate('window.updatesUI.init("test-instance")')
            wait_for(lambda: c.evaluate('document.querySelector("#updates-status").textContent.includes("актуальную")'))
            assert c.evaluate('document.querySelector("#updates-badge").hidden')
            state.update(update_available=True, latest={'version': '0.9.3', 'build': 8,
                         'title': 'Release', 'notes': '<img src=x onerror="window.injected=true">' + 'LongNotes' * 400})
            c.evaluate('window.updatesUI.refresh()')
            wait_for(lambda: c.evaluate('!document.querySelector("#updates-badge").hidden'))
            c.click('#updates-badge')
            assert c.evaluate('document.querySelector("#updates-dialog").open')
            assert c.evaluate('!document.querySelector("#updates-notes img") && !window.injected')
            for width, height in [(1440, 900), (1024, 768), (760, 560), (375, 700)]:
                c.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
                assert c.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
                assert c.evaluate('document.querySelector("#updates-dialog").scrollWidth<=document.querySelector("#updates-dialog").clientWidth'), width
            c.click('#updates-open')
            wait_for(lambda: len(calls) == 1)
            assert calls[0] == ('/api/setup/external', '{"page":"update-release"}')
            c.call('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
            c.call('Input.dispatchKeyEvent', type='keyUp', key='Escape', code='Escape', windowsVirtualKeyCode=27)
            wait_for(lambda: c.evaluate('!document.querySelector("#updates-dialog").open'))
            assert c.evaluate('document.activeElement.id==="updates-badge"')
            c.evaluate('document.querySelector("#desktop-help-menu").open=true')
            c.click('#updates-check')
            wait_for(lambda: len(calls) == 2)
            assert calls[1][0] == '/api/updates/check'
            print('PASS: update badge, text safety, manual check, fixed external command, Escape/focus, 375–1440 px')
            base = f'http://127.0.0.1:{server.server_port}'
            shell = (ROOT / 'video_descriptor/assets/desktop-shell.js').read_text(encoding='utf-8')
            for path in ['/create?job=old&report=old', '/output/', '/help/ollama', '/help/lmstudio']:
                before = len(health_calls)
                c.call('Page.navigate', url=base + path)
                wait_for(lambda: c.evaluate('!!window.updatesUI && !!document.querySelector("#stop")'))
                assert len(health_calls) == before + 1
                c.evaluate(shell)
                assert c.evaluate('document.querySelectorAll(".desktop-menu-bar").length===1 && document.querySelectorAll("#stop").length===1')
                assert c.evaluate('''[...document.querySelectorAll('#desktop-file-menu a')].map(a=>a.getAttribute('href')).join('|')==='/#new|/#records' ''')
                assert c.evaluate('document.querySelector("#setup-open").getAttribute("href")==="/#settings"')
            c.call('Emulation.setDeviceMetricsOverride', width=1440, height=900, deviceScaleFactor=1, mobile=False)
            c.evaluate('window.notesEditorDirty=()=>true;document.querySelector("#desktop-file-menu").open=true')
            c.click('#desktop-file-menu a')
            wait_for(lambda: c.evaluate('document.querySelector(".desktop-command-status").textContent.includes("правки")'))
            assert c.evaluate('location.pathname==="/help/lmstudio" && document.querySelector("#desktop-file-menu").open && document.activeElement===document.querySelector("#desktop-file-menu a")')
            before = len(calls)
            c.click('#stop')
            assert len(calls) == before  # Dirty guard must precede the mutation.
            c.evaluate('window.notesEditorDirty=()=>false')
            c.click('#stop')
            wait_for(lambda: c.evaluate('document.querySelector(".desktop-command-status").textContent.includes("Active fixture")'))
            assert calls[-1][0] == '/api/native/stop'
            assert c.evaluate('!document.querySelector("#stop").disabled && !window.desktopShellStopped && document.activeElement.id==="stop"')
            c.evaluate('document.querySelector("#desktop-file-menu").open=false')
            health_mode['value'] = 'unavailable'
            c.evaluate('desktopShellEnvironment.read(true)')
            assert c.evaluate('!document.querySelector(".desktop-environment-status").hidden && document.querySelector("#stop").disabled')
            health_mode['value'] = 'windows'
            c.click('.desktop-environment-status button')
            wait_for(lambda: c.evaluate('desktopShellEnvironment.read().then(v=>v.kind==="windows")'))
            assert c.evaluate('document.querySelectorAll("#stop").length===1 && document.querySelectorAll("#updates-dialog").length===1')
            health_mode['value'] = 'web'
            c.call('Page.navigate', url=base + '/create?job=old')
            wait_for(lambda: c.evaluate('!!window.desktopShellEnvironment && desktopShellEnvironment.read().then(v=>v.kind==="web")'))
            assert c.evaluate('''!document.querySelector('#stop') && !document.querySelector('#updates-check') &&
              [...document.querySelectorAll('#desktop-file-menu a')].map(a=>a.getAttribute('href')).join('|')==='/create|/output/' ''')
            print('PASS: shared-page commands, canonical routes, one health read, repeated initialization/retry, dirty focus and guarded stop refusal; isolated HTTP only')
        finally:
            for process in reversed(browser.children(recursive=True)):
                try:
                    process.terminate()
                except psutil.NoSuchProcess:
                    pass
            child.terminate()
            child.wait(timeout=10)
            server.shutdown()


if __name__ == '__main__':
    main()
