"""Exercise production workspace in an explicitly selected loopback WebView2.

Run only against disposable acceptance data: the optional edit test saves a reply.
Uses the Sandbox harness CDP transport; no model installation or mock APIs.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).parent / 'sandbox'))
from acceptance_ui import CDP, read_http, wait_for


def installed_workflow(root, port, output, *, with_ollama=False):
    """Called by the installer verifier; all data and processes belong to its fresh installation."""
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        debug_port = probe.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    environment = dict(os.environ, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=
                       f'--remote-debugging-port={debug_port} --remote-debugging-address=127.0.0.1')
    process = subprocess.Popen([str(root / 'windows-app/desktop-sdk/VideoDescriptor.exe'),
                                str(root / 'windows-app'), str(root / 'python/python.exe'),
                                '--ui-test-port=' + str(debug_port)],
                               env=environment, creationflags=0x08000000)
    evidence = {'status': 'FAIL', 'checks': [], 'screens': [], 'installed_root': str(root)}
    cdp = None
    try:
        def attach():
            pages = json.loads(read_http(f'http://127.0.0.1:{debug_port}/json/list'))
            return next((page for page in pages if page.get('type') == 'page'
                         and page.get('url', '').startswith(base + '/')), None)

        target = wait_for(attach, timeout=150)
        cdp = CDP(target['webSocketDebuggerUrl'])
        wait_for(lambda: cdp.evaluate('!!document.querySelector("#setup-finish")'))
        if cdp.evaluate('document.querySelector("#setup-finish").getClientRects().length'):
            cdp.click('#setup-finish')
            wait_for(lambda: cdp.evaluate('location.hash === "#records"'))
        cdp.click('#new-record-open')
        wait_for(lambda: cdp.evaluate('!document.querySelector("#new-record-view").hidden'))
        document = cdp.call('DOM.getDocument')['root']['nodeId']
        node = cdp.call('DOM.querySelector', nodeId=document, selector='#file')['nodeId']
        cdp.call('DOM.setFileInputFiles', nodeId=node, files=[str(root / 'windows-app/samples/speech-check.mp4')])
        cdp.fill('#title', 'Установленная сборка / Встановлена збірка — автоматическая приёмка')
        cdp.fill('#language', 'en')
        wait_for(lambda: not cdp.evaluate('document.querySelector("#start").disabled'))
        cdp.click('#start')
        wait_for(lambda: cdp.visible_text('#status'), lambda value: value in {'Готово', 'Нужна проверка'}, timeout=240)
        job = cdp.evaluate('new URLSearchParams(location.search).get("job")')
        speech = json.loads(read_http(base + '/api/speech?' + urlencode({'job': job})))
        assert speech['job']['status'] == 'done' and speech['result']['segments'], speech
        folder = speech['job']['folder']
        evidence['ui_speech'] = speech
        evidence['checks'].append('installed WebView2 file input, actual MP4 upload, CPU Whisper and saved result')
        notes_folder = None
        if with_ollama:
            for button in ['#translate-run', '#notes-run']:
                cdp.call('Page.navigate', url=base + '/?job=' + job + '#records')
                wait_for(lambda button=button: cdp.evaluate(
                    f'!!document.querySelector({json.dumps(button)})?.getClientRects().length&&!document.querySelector({json.dumps(button)}).disabled'))
                cdp.click(button)
                wait_for(lambda: cdp.evaluate('new URLSearchParams(location.search).get("job")'), lambda value: value and value != job)
                wait_for(lambda: cdp.visible_text('#status'), lambda value: value in {'Готово', 'Нужна проверка'}, timeout=600)
                current = cdp.evaluate('new URLSearchParams(location.search).get("job")')
                result = json.loads(read_http(base + '/api/speech?' + urlencode({'job': current})))
                assert result['job']['status'] == 'done', result
                evidence[button[1:]] = result['job']
                if button == '#notes-run':
                    notes_folder = result['job']['folder']
            evidence['checks'].append('real installed UI Ollama translation and notes in separate versions')
        run(argparse.Namespace(base=base, debug_port=debug_port, target_id=target['id'], folder=folder,
                               notes_folder=notes_folder, output=output, edit_reply=True), evidence)
        evidence['status'] = 'PASS'
        return evidence
    except Exception as error:
        evidence['error'] = f'{type(error).__name__}: {error}'
        evidence['traceback'] = traceback.format_exc()
        raise
    finally:
        (output / 'workspace-ui.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        if cdp:
            cdp.sock.close()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=20)


def installed_component_workflow(root, port, output, model, cache, device):
    """Explicit slow installed UI acceptance; never called by Fast CI or normal smoke."""
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        debug_port = probe.getsockname()[1]
    environment = dict(os.environ, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=
                       f'--remote-debugging-port={debug_port} --remote-debugging-address=127.0.0.1')
    process = subprocess.Popen([str(root / 'windows-app/desktop-sdk/VideoDescriptor.exe'),
                                str(root / 'windows-app'), str(root / 'python/python.exe'),
                                '--ui-test-port=' + str(debug_port)], env=environment, creationflags=0x08000000)
    command = [sys.executable, str(Path(__file__).parent / 'verify_component_ui.py'), '--root', str(root),
               '--reports', str(output), '--debug-port', str(debug_port), '--with-diarization',
               '--ollama-model', model, '--diarization-device', device]
    if cache:
        command += ['--cache', str(cache)]
    try:
        result = subprocess.run(command, check=False, timeout=3600, env=environment)
        report = json.loads((output / 'component-ui.json').read_text(encoding='utf-8'))
        if result.returncode or report['status'] != 'PASS':
            raise RuntimeError('Installed component UI acceptance failed: ' + str(report.get('error', device)))
        return report
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=20)


def run(args, report):
    targets = json.loads(read_http(f'http://127.0.0.1:{args.debug_port}/json/list'))
    matches = [item for item in targets if item.get('type') == 'page'
               and item.get('url', '').startswith(args.base + '/')
               and (not args.target_id or item['id'] == args.target_id)]
    if len(matches) != 1:
        raise ValueError('Expected exactly one WebView2 page for the supplied application')
    cdp = CDP(matches[0]['webSocketDebuggerUrl'])
    cdp.call('Emulation.setDeviceMetricsOverride', width=1200, height=820, deviceScaleFactor=1, mobile=False)
    report['health'] = json.loads(read_http(args.base + '/health'))
    report['rendering'] = 'real WebView2; CSS viewport and DPR emulation, not OS scaling'
    cdp.call('Page.enable')
    cdp.call('Runtime.enable')
    downloads = args.output / 'downloads'
    downloads.mkdir(exist_ok=True)
    cdp.call('Browser.setDownloadBehavior', behavior='allow', downloadPath=str(downloads.resolve()))

    def navigate(path, selector):
        cdp.call('Page.navigate', url=args.base + path)
        wait_for(lambda: cdp.evaluate(f'!!document.querySelector({json.dumps(selector)})'))
        time.sleep(.3)

    def capture(name):
        metrics = cdp.evaluate('''({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,
            scrollWidth:document.documentElement.scrollWidth,
            ids:[...document.querySelectorAll('[id]')].map(e=>e.id),
            missingLabels:[...document.querySelectorAll('input,select,textarea')]
              .filter(e=>!e.hidden&&e.type!=='hidden'&&e.getClientRects().length&&!e.labels?.length&&!e.getAttribute('aria-label')&&!e.getAttribute('aria-labelledby')).map(e=>e.id)})''')
        assert metrics['scrollWidth'] <= metrics['width'] + 1, (name, metrics)
        assert len(metrics['ids']) == len(set(metrics['ids'])), (name, 'duplicate IDs')
        assert not metrics['missingLabels'], (name, metrics['missingLabels'])
        cdp.screenshot(args.output / (name + '.png'))
        report['screens'].append({'name': name, **metrics})

    query = urlencode({'folder': args.folder, 'stage': 'speech', 'acceptance': 'preserved'})
    navigate('/create?' + query, '#speech-feed .edit-subtitle')
    wait_for(lambda: cdp.visible_text('#run-title'))
    if args.edit_reply:
        original = json.loads(read_http(args.base + '/api/speech?' + urlencode({'folder': args.folder})))['result']
        cdp.click('.edit-subtitle')
        wait_for(lambda: cdp.evaluate('!!document.querySelector("dialog.reply-editor[open]")'))
        capture('reply-editor')
        updated = original['segments'][0]['text'] + ' UI acceptance.'
        cdp.fill('.reply-editor textarea[name=left]', updated)
        # Dirty Escape must raise a prompt; dismissing it retains both the text and dialog.
        cdp.call('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
        wait_for(lambda: cdp.evaluate('!!document.querySelector("[data-keep-editing]")'))
        cdp.click('[data-keep-editing]')
        assert cdp.evaluate('document.querySelector(".reply-editor").open')
        assert cdp.evaluate('document.querySelector(".reply-editor textarea").value') == updated
        cdp.click('.reply-editor button[type=submit]')
        wait_for(lambda: cdp.evaluate('!document.querySelector("dialog.reply-editor")'))
        saved = json.loads(read_http(args.base + '/api/speech?' + urlencode({'folder': args.folder})))['result']
        report['reply_save'] = {'before': original['segments'][0], 'after': saved['segments'][0]}
        assert saved['segments'][0]['text'] == updated, 'saved reply text differs'
        # The existing editor presents and saves times at millisecond precision.
        for boundary in ['start', 'end']:
            assert abs(saved['segments'][0][boundary] - original['segments'][0][boundary]) <= .0005, boundary
        assert saved['edit_revision'] != original['edit_revision'], 'revision did not advance'
        report['checks'].append('reply dirty Escape retained input; real save/revision and timestamps verified')
    cdp.click('#tab-source')
    cdp.fill('#source-title', 'Несохранённое название / Незбережена назва')
    cdp.click('#tab-notes')
    cdp.call('Runtime.evaluate', expression='history.back()')
    wait_for(lambda: cdp.evaluate('document.querySelector("#tab-source").getAttribute("aria-selected")==="true"'))
    assert cdp.evaluate('document.querySelector("#source-title").value') == 'Несохранённое название / Незбережена назва'
    assert cdp.evaluate('new URLSearchParams(location.search).get("acceptance")') == 'preserved'
    cdp.click('.vd-global-nav a[href*="#settings"]')
    wait_for(lambda: cdp.evaluate('!!document.querySelector("#records-open")'))
    wait_for(lambda: cdp.evaluate('document.querySelector("#records-open").getAttribute("href").startsWith("/create?")'))
    cdp.click('#records-open')
    wait_for(lambda: cdp.evaluate('!!document.querySelector("#source-title")'))
    wait_for(lambda: cdp.evaluate('document.querySelector("#source-title").value') == 'Несохранённое название / Незбережена назва')
    report['checks'].append('stage Back, query parameters, AI round trip and unsaved title recovery')
    cdp.click('#tab-notes')
    cdp.evaluate('document.querySelector("#prompt-settings-panel").open=true')
    tasks=cdp.evaluate('[...document.querySelector("#prompt-task").options].map(e=>e.value)')
    assert len(tasks)>1
    cdp.fill('#prompt-task',tasks[0]);cdp.fill('#model-prompt','Acceptance draft A / черновик A')
    cdp.fill('#prompt-task',tasks[1]);cdp.fill('#model-prompt','Acceptance draft B / чернетка B')
    cdp.click('.vd-global-nav a[href*="#settings"]')
    wait_for(lambda:cdp.evaluate('document.querySelector("#records-open")?.getAttribute("href").startsWith("/create?")'))
    cdp.click('#records-open')
    wait_for(lambda:cdp.evaluate('document.querySelector("#prompt-task")?.options.length>1'))
    assert cdp.evaluate('document.querySelector("#prompt-task").value')==tasks[1]
    assert cdp.evaluate('document.querySelector("#model-prompt").value')=='Acceptance draft B / чернетка B'
    cdp.fill('#prompt-task',tasks[0])
    assert cdp.evaluate('document.querySelector("#model-prompt").value')=='Acceptance draft A / черновик A'
    report['checks'].append('two independent prompt drafts and selected task survive AI navigation')

    cdp.click('#tab-speech')
    for selector, extension in [('#download-srt', '.srt'), ('#download-subtitles', '.vtt'), ('#download-transcript', '.txt')]:
        # Returning from AI settings reloads the workspace asynchronously.
        wait_for(lambda selector=selector: cdp.evaluate(
            f'(() => {{const e=document.querySelector({json.dumps(selector)});return !!e?.getClientRects().length&&!!e.href&&!e.hidden;}})()'))
        cdp.click(selector)
        wait_for(lambda extension=extension: list(downloads.glob('*' + extension)))
    report['checks'].append('real SRT/VTT/TXT downloads through production links')
    cdp.click('#tab-source')
    cdp.call('Input.dispatchKeyEvent',type='keyDown',key='ArrowRight',code='ArrowRight',windowsVirtualKeyCode=39)
    assert cdp.evaluate('document.querySelector("#tab-speech").getAttribute("aria-selected")==="true"&&document.activeElement.id==="tab-speech"')
    report['checks'].append('keyboard stage arrows update selection and focus')
    cdp.evaluate('document.querySelector(".vd-skip").focus()')
    cdp.click('.vd-skip')
    assert cdp.evaluate('document.activeElement.id==="stage-speech"'), 'skip link did not focus the current stage'
    report['checks'].append('skip link focuses the active stage without losing URL context')
    cdp.call('Emulation.setDeviceMetricsOverride',width=760,height=560,deviceScaleFactor=1,mobile=False)
    cdp.evaluate("""(() => {const feed=document.querySelector('#speech-feed'),template=feed.querySelector('.utterance');
      if(!template)throw Error('No real utterance to stress');
      const rows=document.createDocumentFragment();for(let i=0;i<1000;i++){
        const row=template.cloneNode(true);row.querySelector('p').textContent=('Длинная расшифровка / Довга розшифровка '+i+' ').repeat(20);rows.append(row);
      }feed.append(rows);feed.scrollIntoView({block:'center'});})()""")
    capture('visual-stress-1000-utterances')
    report['checks'].append('visual-only DOM stress fixture: 1000 long RU/UK utterances; no API/mock inference claim')
    navigate('/create?' + query,'#speech-feed .edit-subtitle')

    for width, height in [(760, 560), (1024, 768), (1200, 820), (1440, 900)]:
        cdp.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
        for stage in ['source', 'speech', 'notes']:
            cdp.click('#tab-' + stage)
            cdp.evaluate('scrollTo(0,0)')
            capture(f'{stage}-{width}x{height}')
        navigate('/output/', '#records')
        capture(f'library-{width}x{height}')
        navigate('/create?' + query, '#speech-feed .edit-subtitle')
    if args.notes_folder:
        navigate('/create?' + urlencode({'folder': args.notes_folder, 'stage': 'notes'}), '#report-editor')
        wait_for(lambda: cdp.evaluate('!!document.querySelector("#report-editor").contentDocument?.querySelector("#save-notes")'))
        wait_for(lambda: cdp.evaluate('!document.querySelector("#report-editor").contentDocument.querySelector("#editor-status").textContent.includes("Открываем")'))

        def frame_click(selector):
            point = cdp.evaluate(f"""(() => {{const frame=document.querySelector('#report-editor');
                frame.scrollIntoView({{block:'center'}});
                const element=frame.contentDocument.querySelector({json.dumps(selector)});
                element.scrollIntoView({{block:'center'}});
                const r=element.getBoundingClientRect(),f=frame.getBoundingClientRect();
                return [f.x+r.x+r.width/2,f.y+r.y+r.height/2];}})()""")
            for action in ['mousePressed', 'mouseReleased']:
                cdp.call('Input.dispatchMouseEvent', type=action, x=point[0], y=point[1], button='left', clickCount=1)

        frame_click('[data-notes-view=edit]')
        cdp.evaluate('document.querySelector("#report-editor").contentDocument.querySelector(".CodeMirror textarea").focus()')
        cdp.call('Input.dispatchKeyEvent', type='keyDown', key='End', code='End', windowsVirtualKeyCode=35, modifiers=2)
        cdp.call('Input.insertText', text='\n\nПроверка сохранения конспекта / Перевірка збереження.\n')
        assert cdp.evaluate('document.querySelector("#report-editor").contentWindow.notesEditorDirty()')
        frame_click('#save-notes')
        wait_for(lambda: cdp.evaluate('!document.querySelector("#report-editor").contentWindow.notesEditorDirty()'))
        for selector, pattern in [('#download-notes', '*.md'), ('#download-html', '*.html')]:
            frame_click(selector)
            wait_for(lambda pattern=pattern: list(downloads.glob(pattern)))
        html = next(downloads.glob('*.html')).read_text(encoding='utf-8')
        assert '<script' not in html.lower() and 'Перевірка збереження' in html
        frame_click('[data-notes-view=read]')
        for width, height in [(760, 560), (1024, 768), (1200, 820), (1440, 900)]:
            cdp.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
            cdp.evaluate('document.querySelector("#report-editor-card").scrollIntoView({block:"start"})')
            capture(f'notes-editor-{width}x{height}')
        report['checks'].append('real generated notes: edit/save, Markdown/HTML downloads, sanitized HTML text and four viewports')
        navigate('/create?' + query, '#speech-feed .edit-subtitle')
    for scale in [1.25, 1.5]:
        cdp.call('Emulation.setDeviceMetricsOverride', width=760, height=560, deviceScaleFactor=scale, mobile=False)
        capture(f'speech-dpr-{scale}')
    cdp.call('Emulation.clearDeviceMetricsOverride')
    report['checks'].append('four requested CSS viewport sizes and 125/150 percent DPR; no horizontal overflow')
    cdp.sock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--target-id')
    parser.add_argument('--debug-port', type=int, default=9222)
    parser.add_argument('--folder', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--notes-folder')
    parser.add_argument('--edit-reply', action='store_true', help='Save a test edit in this disposable result')
    args = parser.parse_args()
    if urlsplit(args.base).hostname != '127.0.0.1':
        parser.error('Only an explicit loopback application is supported')
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'status': 'FAIL', 'checks': [], 'screens': []}
    try:
        run(args, report)
        report['status'] = 'PASS'
    except Exception as error:  # noqa: BLE001 -- preserve acceptance failure evidence
        report['error'] = f'{type(error).__name__}: {error}'
    (args.output / 'workspace-ui.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in {'screens', 'health'}}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
