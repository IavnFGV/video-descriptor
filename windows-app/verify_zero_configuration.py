"""Acceptance of contextual speakers through a marked installed WebView2 test app."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'sandbox'))
from acceptance_ui import CDP, read_http, wait_for


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--reports', required=True, type=Path)
    parser.add_argument('--installed', action='store_true', help='Caller confirms this payload was installed by the tested installer')
    parser.add_argument('--debug-port', type=int, default=9222)
    parser.add_argument('--device', choices=['cpu', 'xpu', 'auto'], default='cpu')
    args = parser.parse_args()
    if not (args.root / '.acceptance-installation.json').is_file():
        raise SystemExit('Only marked disposable test installations are supported')
    pages = json.loads(read_http(f'http://127.0.0.1:{args.debug_port}/json/list'))
    page = next(item for item in pages if item['type'] == 'page' and item['url'].startswith('http://127.0.0.1:'))
    cdp = CDP(page['webSocketDebuggerUrl'])
    report = {'status': 'FAIL', 'method': 'real WebView2 pointer/form input', 'installed': args.installed, 'device': args.device}
    started = time.monotonic()
    try:
        origin = cdp.evaluate('location.origin')
        def api(path):
            return json.loads(read_http(origin + path))
        assert api('/health')['installation'] == hashlib.sha256(str(args.root / 'windows-app').encode()).hexdigest()
        state = json.loads((args.reports / 'workflow-state.json').read_text(encoding='utf-8-sig'))
        source = state['source_job']
        cdp.call('Page.navigate', url=origin + '/?job=' + source)
        wait_for(lambda: cdp.visible_text('#status') == 'Готово')
        before = api('/api/speech?job=' + source)['result']['segments']
        cdp.click('#diarize-run')
        wait_for(lambda: cdp.evaluate('document.querySelector("#speaker-dialog").open'))
        wait_for(lambda: cdp.visible_text('#speaker-status'), lambda value: 'Потребуется' in value or 'найдено' in value or 'Готово' in value)
        cdp.fill('#speaker-device', args.device)
        if not cdp.evaluate('document.querySelector("#speaker-install-fields").hidden'):
            cdp.click('#speaker-consent')
        cdp.screenshot(args.reports / 'zero-config-speaker-install.png')
        cdp.click('#speaker-go')
        def completed():
            identity = cdp.evaluate('new URLSearchParams(location.search).get("job")')
            if identity != source:
                result = api('/api/speech?job=' + identity)
                if result['job']['status'] == 'error':
                    raise RuntimeError(result['job'].get('error', 'Speaker job failed'))
                if result['job']['status'] == 'done' and result.get('result', {}).get('diarization_device'):
                    return identity
            if cdp.evaluate('document.querySelector("#speaker-dialog").open && !document.querySelector("#speaker-go").disabled'):
                raise RuntimeError(cdp.visible_text('#speaker-status'))
            return None
        job = wait_for(completed, timeout=1200)
        result = api('/api/speech?job=' + job)
        assert result['result'].get('diarization_device') in ({'cpu', 'xpu'} if args.device == 'auto' else {args.device})
        assert api('/api/speech?job=' + source)['result']['segments'] == before
        report.update(status='PASS', original_preserved=True, result_device=result['result']['diarization_device'],
                      segments=len(result['result']['segments']), resumed_job=job)
        cdp.screenshot(args.reports / 'zero-config-speaker-result.png')
    except Exception as exc:  # noqa: BLE001 — persist acceptance evidence
        report['error'] = str(exc)
    finally:
        report['seconds'] = round(time.monotonic() - started, 2)
        (args.reports / 'contextual-speakers.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        cdp.sock.close()
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
