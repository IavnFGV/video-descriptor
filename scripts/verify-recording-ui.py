"""Isolated browser acceptance: real UI/assets and temporary recording artifacts."""
import json
import socket
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'windows-app/sandbox'))
from acceptance_ui import CDP, read_http, wait_for

from video_descriptor import construction, live
from video_descriptor.jobs import write_json
from video_descriptor.models import Source
from video_descriptor.report import render
from video_descriptor.serve import RangeRequestHandler

out = ROOT / 'windows-app/runtime/zero-config/unified-recording'
out.mkdir(parents=True, exist_ok=True)
live.active_video = lambda _: False
with tempfile.TemporaryDirectory(prefix='vd-unified-') as temporary:
    root = Path(temporary)
    video = root / 'data/meeting.mp4'
    video.parent.mkdir(); video.write_bytes(b'fixture')
    for name, model in [('original', ''), ('notes-a', 'model-a'), ('notes-b', 'model-b')]:
        folder = root / 'output' / name; folder.mkdir(parents=True)
        rows = [{'id': f's{i}', 'start': i*30, 'end': i*30+30, 'text': f'Реплика {i}. Проверка синхронизации и правок.', 'speaker':'speaker_1'} for i in range(80)]
        write_json(folder / 'manifest.json', {'video': str(video), 'processed_duration': 2400})
        write_json(folder / 'speech.json', {'folder': name, 'status': 'done', 'engine': 'whisper-local', 'segments': rows, 'speaker_names': {'speaker_1':'Саша'}})
        write_json(folder / 'transcript.json', rows)
        write_json(folder / 'frames.json', [])
        if model:
            write_json(folder / 'construction-settings.json', construction.validate({'model': model}))
            write_json(folder / 'notes.json', {'notes': [], 'sections': []})
            render(folder, video, [Source(**{k:v for k,v in row.items() if k!='speaker'}) for row in rows], [])
            (folder / 'notes.user.md').write_text('## [00:00:00] Начало\n\n'+('Описание.\n\n'*45)+'## [00:01:00] Раздел второй\n\n'+('Подробности.\n\n'*45), encoding='utf-8')
    identity='a'*32
    job_folder=root/'output/jobs'/identity;job_folder.mkdir(parents=True)
    write_json(job_folder/'job.json',{'id':identity,'video':str(video),'filename':video.name,'folder':'notes-a','status':'done','mode':'postprocess','task':'notes','created':1})
    class Handler(RangeRequestHandler):
        def do_GET(self):
            path=urlsplit(self.path).path
            if path=='/health':return self.json_response(200,{'status':'ok','app':'video-descriptor-windows','instance':'fixture'})
            name={'/':'index.html','/native.js':'app.js','/native.css':'app.css'}.get(path)
            if name:
                body=(ROOT/'windows-app/ui'/name).read_bytes()
                self.send_response(200);self.send_header('Content-Type',{'html':'text/html','js':'text/javascript','css':'text/css'}[name.rsplit('.',1)[1]]+'; charset=utf-8');self.end_headers();self.wfile.write(body);return
            return super().do_GET()
    server = ThreadingHTTPServer(('127.0.0.1',0), partial(Handler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with socket.socket() as probe: probe.bind(('127.0.0.1',0)); debug=probe.getsockname()[1]
    child=subprocess.Popen([r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe','--headless=new','--disable-gpu','--no-first-run',f'--user-data-dir={root / "edge"}',f'--remote-debugging-port={debug}','about:blank'],creationflags=0x08000000,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        tabs=wait_for(lambda:json.loads(read_http(f'http://127.0.0.1:{debug}/json/list')),timeout=30)
        c=CDP(next(tab for tab in tabs if tab.get('type')=='page')['webSocketDebuggerUrl'])
        c.call('Page.enable')
        c.call('Page.addScriptToEvaluateOnNewDocument',source="""window.uiErrors=[];addEventListener('error',e=>uiErrors.push(e.message));Object.defineProperties(HTMLMediaElement.prototype,{readyState:{get:()=>2},duration:{get:()=>2400},currentTime:{get(){return this._time||0},set(v){this._time=v;this.dispatchEvent(new Event('timeupdate'))}}});HTMLMediaElement.prototype.load=function(){};""")
        c.call('Emulation.setDeviceMetricsOverride',width=1920,height=1080,deviceScaleFactor=1,mobile=False)
        c.call('Page.navigate',url=f'http://127.0.0.1:{server.server_port}/?job={identity}')
        wait_for(lambda:c.evaluate('!!document.querySelector("#recording-notes")?.options.length && !!document.querySelector("#report-editor")?.contentDocument?.querySelector("#personal-preview [data-note-time]")'),timeout=35)
        def evaluate(script): return c.evaluate(script)
        assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
        assert evaluate('location.pathname==="/create" && recordingUI.native')
        assert evaluate('document.querySelectorAll("#process-video").length') == 1
        assert not evaluate('document.querySelector("#report-editor").contentDocument.querySelector("video")?.hasAttribute("src")')
        geometry=evaluate('''(()=>{const r=id=>{const a=document.getElementById(id).getBoundingClientRect();return {x:a.x,y:a.y,w:a.width,h:a.height}};return {video:r('shared-player'),speech:r('stage-speech'),notes:r('stage-notes')}})()''')
        print('Geometry:',geometry,flush=True)
        assert geometry['speech']['y']>geometry['video']['y']
        assert geometry['speech']['x']==geometry['video']['x']
        assert geometry['notes']['x']>geometry['video']['x']+geometry['video']['w']
        evaluate('window.originalPlayer=document.querySelector("#process-video");recordingUI.seek(75)')
        assert evaluate('document.querySelector("#process-video").currentTime')==75
        assert evaluate('document.querySelector("#speech-feed .active").textContent.includes("Реплика 2")')
        assert evaluate('document.querySelector("#report-editor").contentDocument.querySelector(".current-note").dataset.noteTime')=='60'
        c.click('#expand-player')
        assert evaluate('document.querySelector("#process-video")===originalPlayer && originalPlayer.currentTime===75')
        assert evaluate('document.querySelector("#shared-player").getBoundingClientRect().width>document.querySelector("#stage-notes").getBoundingClientRect().width*1.8')
        c.click('#expand-player')
        c.fill('#recording-notes','/output/notes-b/report.html')
        wait_for(lambda:evaluate('location.search.includes("notes-b") && document.querySelector("#report-editor").src.includes("notes-b")'),timeout=15)
        assert evaluate('document.querySelector("#process-video")===originalPlayer && originalPlayer.currentTime===75')
        wait_for(lambda:evaluate('!!document.querySelector("#report-editor").contentDocument.querySelector("#personal-preview [data-note-time]")'))
        evaluate('document.querySelector("#report-editor").contentWindow.notesEditorDirty=()=>true')
        c.fill('#recording-notes','/output/notes-a/report.html')
        assert evaluate('location.search.includes("notes-b")')
        assert 'Сохраните' in c.visible_text('#recording-status')
        evaluate('document.querySelector("#report-editor").contentWindow.notesEditorDirty=()=>false')
        evaluate('recordingUI.pauseLink();originalPlayer.currentTime=600')
        assert not evaluate('document.querySelector("#resume-playback-link").hidden')
        c.click('#resume-playback-link')
        assert evaluate('document.querySelector("#resume-playback-link").hidden')
        c.click('#playback-link')
        assert not evaluate('recordingUI.linked()')
        c.fill('#recording-notes','__new__')
        assert not evaluate('document.querySelector("#recording-notes-settings").hidden')
        assert evaluate('document.querySelector("#report-editor").src.includes("notes-b")')
        c.fill('#construction-provider','gemini')
        c.click('#construction-run')
        assert 'Подтвердите отправку' in c.visible_text('#construction-status')
        c.click('#cancel-new-notes')
        c.fill('#recording-speech','__new__')
        assert evaluate('document.querySelector("#speech-settings").open')
        evaluate('document.querySelector("#speech-settings").open=false;scrollTo(0,0)')
        c.screenshot(out/'full-hd.png')
        for width in (1100,760,360):
            c.call('Emulation.setDeviceMetricsOverride',width=width,height=900,deviceScaleFactor=1,mobile=False)
            assert evaluate('document.documentElement.scrollWidth<=innerWidth'), width
        c.screenshot(out/'narrow.png')
        assert evaluate('window.uiErrors')==[], evaluate('window.uiErrors')
        evidence={'status':'PASS','scope':'Isolated Edge, real production HTML/JS, temporary speech/report artifacts, mocked native health and media metadata; no inference or user data', 'checks':['native job URL opens unified workspace directly','one shared player; embedded report has no media source','side layout: speech under video, notes right','expanded layout','player identity and time preserved across report variants','speech and Markdown heading synchronization','manual scroll pause and resume','magnet off','dirty report blocks variant switch','new notes settings preserve existing report','Google generation requires consent before submission','new speech settings','1920/1100/760/360 widths fit','no browser runtime errors']}
        (out/'result.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(evidence,ensure_ascii=False))
    finally:
        child.terminate();child.wait(timeout=15);server.shutdown();server.server_close()
