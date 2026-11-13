"""Task 6: isolated Edge checks; no application server or recording data."""
import argparse
import base64
import json
import socket
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'windows-app/sandbox'))
from acceptance_ui import CDP, read_http, wait_for


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    requests = []

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            super().do_GET()

        def log_message(self, *_):
            pass

    with tempfile.TemporaryDirectory(prefix='vd-tabs-') as temporary:
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT / 'design-system')))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        child = subprocess.Popen([
            r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
            '--headless=new', '--disable-gpu', '--no-first-run',
            f'--user-data-dir={temporary}/edge', f'--remote-debugging-port={port}',
            'about:blank',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        browser = psutil.Process(child.pid)
        c = None
        try:
            tabs = wait_for(lambda: json.loads(read_http(f'http://127.0.0.1:{port}/json/list')), timeout=30)
            c = CDP(next(tab for tab in tabs if tab.get('type') == 'page')['webSocketDebuggerUrl'])
            c.call('Page.enable')
            c.call('Page.addScriptToEvaluateOnNewDocument', source="""
                window.uiErrors=[];window.forbidden=[];
                addEventListener('error',e=>uiErrors.push(e.message));
                for(const key of ['fetch','XMLHttpRequest','WebSocket','EventSource'])
                  window[key]=function(){forbidden.push(key);throw Error('No network permitted')};
                for(const key of ['getItem','setItem','removeItem','clear'])
                  Storage.prototype[key]=function(){forbidden.push('storage');throw Error('No storage permitted')};
                for(const key of ['pushState','replaceState'])
                  history[key]=function(){forbidden.push('history');throw Error('No routing permitted')};
                """)
            url = f'http://127.0.0.1:{server.server_port}/prototype/workspace-tabs.html'
            c.call('Page.navigate', url=url)
            wait_for(lambda: c.evaluate('document.readyState==="complete" && !!document.querySelector("#tab-speech")'))
            c.evaluate('window.originalPlayer=document.querySelector("#player");window.originalDraft=document.querySelector("#material-draft")')

            def key(name, shift=False):
                for event in ['keyDown', 'keyUp']:
                    c.call('Input.dispatchKeyEvent', type=event, key=name, modifiers=8 if shift else 0)

            def selected(ident):
                assert c.evaluate(f'document.querySelector("#{ident}").getAttribute("aria-selected")==="true"'), ident

            def capture(name):
                c.evaluate('window.scrollTo(0,0)')
                size = c.call('Page.getLayoutMetrics')['cssContentSize']
                size['width'] = max(size['width'], c.evaluate('innerWidth'))
                image = c.call('Page.captureScreenshot', format='png', captureBeyondViewport=True,
                               clip={**size, 'scale': 1})
                (output / f'{name}.png').write_bytes(base64.b64decode(image['data']))

            for width, height in [(1440, 900), (1200, 820), (1024, 768), (760, 560), (375, 820)]:
                c.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
                for scenario in ['ready', 'empty', 'busy', 'error']:
                    c.fill('#scenario', scenario)
                    for area in ['speech', 'translation', 'materials']:
                        c.click(f'#tab-{area}')
                        selected(f'tab-{area}')
                        assert c.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth'), (width, scenario, area)
                        assert c.evaluate('document.querySelector("#player").checkVisibility() && document.querySelector("#operation").checkVisibility()')
                        assert c.evaluate('document.querySelectorAll(".workspace > [role=tabpanel]:not([hidden])").length===1')
                        if area == 'materials':
                            c.click('#tab-article')
                            assert c.evaluate('!document.querySelector("#empty-material").hidden') == (scenario == 'empty')
                            assert c.evaluate('document.querySelector("#material-draft").checkVisibility()') == (scenario != 'empty')
                        if scenario == 'busy':
                            assert c.evaluate('!document.querySelector("#stop").disabled && !document.querySelector("#operation-progress").hasAttribute("value")')
                        if scenario == 'error':
                            assert c.evaluate('!document.querySelector("#recover").disabled && document.querySelector("#operation-error").checkVisibility()')
                    capture(f'{width}-{scenario}')

            c.call('Emulation.setDeviceMetricsOverride', width=1440, height=900, deviceScaleFactor=1, mobile=False)
            c.fill('#scenario', 'ready')
            c.click('#tab-speech')
            for name, expected in [('ArrowLeft', 'materials'), ('ArrowRight', 'speech'), ('End', 'materials'), ('Home', 'speech')]:
                key(name)
                selected(f'tab-{expected}')
                assert c.evaluate(f'document.activeElement.id==="tab-{expected}"')
            # A single Tab leaves each tablist; Shift+Tab returns to the selected tab.
            key('Tab')
            assert c.evaluate('document.activeElement.id==="panel-speech"')
            key('Tab', shift=True)
            assert c.evaluate('document.activeElement.id==="tab-speech"')
            c.click('#tab-materials')
            c.click('#tab-notes')
            for name, expected in [('ArrowLeft', 'article'), ('ArrowRight', 'notes'), ('End', 'article'), ('Home', 'notes')]:
                key(name)
                selected(f'tab-{expected}')
                selected('tab-materials')
                assert c.evaluate(f'document.querySelector("#material-panel").getAttribute("aria-labelledby")==="tab-{expected}"')
            key('Tab')
            assert c.evaluate('document.activeElement.id==="material-panel"')
            key('Tab', shift=True)
            assert c.evaluate('document.activeElement.id==="tab-notes"')
            assert c.evaluate('getComputedStyle(document.activeElement).outlineStyle==="solid" && getComputedStyle(document.activeElement).outlineWidth==="3px"')
            capture('keyboard-focus')
            c.fill('#material-draft', 'Synthetic unsaved draft')
            c.click('#tab-translation')
            c.click('#tab-materials')
            assert c.evaluate('originalDraft===document.querySelector("#material-draft") && originalDraft.value==="Synthetic unsaved draft" && originalPlayer===document.querySelector("#player")')
            c.click('#tab-article')
            c.fill('#scenario', 'empty')
            c.click('#tab-notes')
            assert c.evaluate('originalDraft.value==="Synthetic unsaved draft" && originalDraft.checkVisibility()')
            c.fill('#scenario', 'busy')
            c.click('#stop')
            assert 'Имитация остановки' in c.visible_text('#operation-status')
            c.fill('#scenario', 'error')
            c.click('#tab-speech')
            c.click('#recover')
            assert 'Реальная операция не запускалась' in c.visible_text('#operation-status')
            c.call('Emulation.setEmulatedMedia', features=[{'name': 'forced-colors', 'value': 'active'}])
            c.click('#tab-materials')
            capture('forced-colors')
            c.call('Emulation.setEmulatedMedia', features=[])
            # 200% zoom-equivalent CSS viewport; not Windows scaling acceptance.
            c.call('Emulation.setDeviceMetricsOverride', width=720, height=450, deviceScaleFactor=2, mobile=False)
            assert c.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth')
            capture('zoom-equivalent')
            assert c.evaluate('window.uiErrors') == []
            assert c.evaluate('window.forbidden') == []
            assert c.evaluate('location.href') == url
            assert all(urlsplit(path).path in ['/prototype/workspace-tabs.html', '/tokens.css', '/components.css', '/favicon.ico'] for path in requests), requests
            (output / 'result.json').write_text(json.dumps({
                'status': 'PASS', 'browser': c.call('Browser.getVersion')['product'],
                'requests': requests, 'captures': 23,
            }, indent=2), encoding='utf-8')
            print(f'PASS: 60 responsive state/area combinations, keyboard, focus, persistent DOM/draft, stop/recovery, no API/storage/history. Captures: {output}')
        finally:
            if c:
                c.sock.close()
            processes = browser.children(recursive=True) if browser.is_running() else []
            for process in reversed(processes):
                try:
                    process.terminate()
                except psutil.NoSuchProcess:
                    pass
            if browser.is_running():
                browser.terminate()
            psutil.wait_procs([browser, *processes], timeout=10)
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'windows-app/runtime/zero-config/workspace-prototype')
    run(parser.parse_args().output.resolve())
