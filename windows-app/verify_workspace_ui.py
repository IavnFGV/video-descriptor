"""Exercise production workspace in an explicitly selected loopback WebView2.

Run only against disposable acceptance data: the optional edit test saves a reply.
Uses the Sandbox harness CDP transport; no model installation or mock APIs.
"""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).parent / 'sandbox'))
from acceptance_ui import CDP, read_http, wait_for


def run(args, report):
    targets = json.loads(read_http(f'http://127.0.0.1:{args.debug_port}/json/list'))
    matches = [item for item in targets if item.get('type') == 'page'
               and item.get('url', '').startswith(args.base + '/')]
    if len(matches) != 1:
        raise ValueError('Expected exactly one WebView2 page for the supplied application')
    cdp = CDP(matches[0]['webSocketDebuggerUrl'])
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
        assert saved['segments'][0]['text'] == updated
        assert saved['segments'][0]['start'] == original['segments'][0]['start']
        assert saved['segments'][0]['end'] == original['segments'][0]['end']
        assert saved['edit_revision'] != original['edit_revision']
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
    cdp.click('#tab-speech')
    for selector, extension in [('#download-srt', '.srt'), ('#download-subtitles', '.vtt'), ('#download-transcript', '.txt')]:
        cdp.click(selector)
        wait_for(lambda extension=extension: list(downloads.glob('*' + extension)))
    report['checks'].append('real SRT/VTT/TXT downloads through production links')
    for width, height in [(760, 560), (1024, 768), (1200, 820), (1440, 900)]:
        cdp.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
        for stage in ['source', 'speech', 'notes']:
            cdp.click('#tab-' + stage)
            cdp.evaluate('scrollTo(0,0)')
            capture(f'{stage}-{width}x{height}')
        navigate('/output/', '#records')
        capture(f'library-{width}x{height}')
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
    parser.add_argument('--debug-port', type=int, default=9222)
    parser.add_argument('--folder', required=True)
    parser.add_argument('--output', type=Path, required=True)
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
