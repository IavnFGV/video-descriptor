"""Real pointer acceptance of one-time preparation in a marked disposable app.

Caller provides an isolated running WebView2 and an existing Whisper model.
This verifier never installs dependencies or authorizes a model download.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'sandbox'))
from acceptance_ui import CDP, read_http, wait_for

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--reports', type=Path, required=True)
parser.add_argument('--debug-port', type=int, default=9222)
args = parser.parse_args()
if not (args.root / '.acceptance-installation.json').is_file():
    raise SystemExit('Only marked disposable test applications are supported')
args.reports.mkdir(parents=True, exist_ok=True)
debug_port = args.debug_port
report = {'status': 'FAIL', 'scope': 'real isolated WebView2, existing speech model, no model downloads'}
cdp = None
try:
    pages=wait_for(lambda:[p for p in json.loads(read_http(f'http://127.0.0.1:{debug_port}/json/list')) if p['type']=='page' and p['url'].startswith('http://127.0.0.1:')],timeout=90)
    page=next(p for p in pages if p['type']=='page' and p['url'].startswith('http://127.0.0.1:'))
    cdp=CDP(page['webSocketDebuggerUrl'])
    origin=cdp.evaluate('location.origin')
    def api(path):return json.loads(read_http(origin+path))
    assert api('/health')['installation']==hashlib.sha256(str(args.root/'windows-app').encode()).hexdigest()
    assert api('/api/setup')['model_present'], 'This focused verifier requires an existing speech model; no download is authorized'
    wait_for(lambda:cdp.evaluate('!document.querySelector("#setup-callout").hidden'))
    cdp.screenshot(args.reports/'startup-callout.png')
    cdp.click('#setup-callout a')
    wait_for(lambda:not cdp.evaluate('document.querySelector("#prepare-selected").disabled'))
    cdp.click('#prepare-selected')
    wait_for(lambda:'Отметьте разрешение' in cdp.visible_text('#preparation-status'))
    assert not api('/api/components').get('preparation',{}).get('state')
    wait_for(lambda:cdp.evaluate('document.activeElement.id')=='prepare-consent')
    report['focus_after_refusal']='prepare-consent'
    wait_for(lambda:not api('/api/doctor')['compute']['preparing'],timeout=120)
    cdp.click('#prepare-consent')
    cdp.screenshot(args.reports/'settings-consent.png')
    cdp.click('#prepare-selected')
    wait_for(lambda:api('/api/components').get('preparation',{}).get('state') in ['running','ready'])
    cdp.click('#records-open')
    def complete():
        plan=api('/api/components').get('preparation',{})
        if plan.get('state')=='error':raise RuntimeError(plan['message'])
        return plan if plan.get('state')=='ready' else None
    report['preparation']=wait_for(complete,timeout=240)
    cdp.click('#setup-open')
    wait_for(lambda:'Выбранные функции готовы' in cdp.visible_text('#preparation-status'))
    widths=[]
    for width,height in [(760,560),(1024,768),(1200,820)]:
        cdp.call('Emulation.setDeviceMetricsOverride',width=width,height=height,deviceScaleFactor=1.5,mobile=False)
        assert cdp.evaluate('document.documentElement.scrollWidth<=innerWidth')
        widths.append(width)
    wait_for(lambda:'Распознавание готово' in cdp.visible_text('#system-status'))
    cdp.evaluate('document.querySelector("#preparation-status").scrollIntoView({block:"center"})')
    cdp.screenshot(args.reports/'settings-ready.png')
    report.update(status='PASS',consent_refusal_starts_nothing=True,completed_after_leaving_settings=True,no_horizontal_overflow=widths)
except Exception as exc:  # noqa: BLE001 — acceptance evidence boundary.
    report['error'] = repr(exc)
finally:
    (args.reports / 'preparation-ui.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if cdp:
        cdp.sock.close()
print(json.dumps(report, ensure_ascii=False))
raise SystemExit(0 if report['status'] == 'PASS' else 1)
