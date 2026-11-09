"""Isolated browser acceptance: real UI/assets and temporary recording artifacts."""
import json
import socket
import subprocess
import sys
import tempfile
import time

import psutil
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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
    for name, model in [('original', ''), ('notes-a', 'model-a'), ('notes-b', 'model-b'), ('article-a', 'model-a')]:
        folder = root / 'output' / name; folder.mkdir(parents=True)
        rows = [{'id': f's{i}', 'start': i*30, 'end': i*30+30, 'text': f'Реплика {i}. Проверка синхронизации и правок.', 'speaker':'speaker_1'} for i in range(80)]
        write_json(folder / 'manifest.json', {'video': str(video), 'processed_duration': 2400})
        write_json(folder / 'speech.json', {'folder': name, 'status': 'done', 'engine': 'whisper-local', 'segments': rows, 'speaker_names': {'speaker_1':'Саша'}})
        write_json(folder / 'transcript.json', rows)
        write_json(folder / 'translations.json', {'s0':'Сохранённый перевод'})
        write_json(folder / 'frames.json', [])
        if model:
            write_json(folder / 'construction-settings.json', construction.validate({'model': model, 'result_kind': 'article' if name == 'article-a' else 'notes'}))
            write_json(folder / 'notes.json', {'notes': [], 'sections': []})
            render(folder, video, [Source(**{k:v for k,v in row.items() if k!='speaker'}) for row in rows], [])
            (folder / 'notes.user.md').write_text('## [00:00:00] Начало\n\n'+('Описание.\n\n'*45)+'## [00:01:00] Раздел второй\n\n'+('Подробности.\n\n'*45), encoding='utf-8')
    identity='a'*32
    job_folder=root/'output/jobs'/identity;job_folder.mkdir(parents=True)
    write_json(job_folder/'job.json',{'id':identity,'video':str(video),'filename':video.name,'folder':'notes-a','status':'done','mode':'postprocess','task':'notes','created':1})
    if '--recovery-only' in sys.argv:
        from video_descriptor import serve
        serve.start_worker = lambda _: None
        failed = root / 'output/failed-notes'
        failed.mkdir()
        for name in ['manifest.json', 'speech.json']:
            (failed/name).write_bytes((root/'output/original'/name).read_bytes())
        write_json(failed/'construction-settings.json', construction.validate({}))
        write_json(failed/'construction-error.json', {'error':'Invalid source timestamps'})
        raw = '## Оглавление\n### [00:00:05] Topic\n\n## Конспект\n### [00:00:05] Topic\nSummary.'
        (failed/'construction-result.md').write_text(raw, encoding='utf-8')
        write_json(job_folder/'job.json', {'id':identity,'video':str(video),'filename':video.name,'folder':'failed-notes','status':'error','stage':'notes','mode':'postprocess','task':'notes','created':1})
    class Handler(RangeRequestHandler):
        def do_GET(self):
            path=urlsplit(self.path).path
            if path=='/health':return self.json_response(200,{'status':'ok','app':'video-descriptor-windows','instance':'fixture'})
            if path=='/api/construction-models':
                provider=parse_qs(urlsplit(self.path).query).get('provider',['ollama'])[0]
                names=['gemini-test'] if provider=='gemini' else ['qwen3.5:9b','model-a','model-b','gpt-oss:20b']
                return self.json_response(200,[{'id':name,'title':name} for name in names])
            name={'/':'index.html','/native.js':'app.js','/native.css':'app.css'}.get(path)
            if name:
                body=(ROOT/'windows-app/ui'/name).read_bytes()
                self.send_response(200);self.send_header('Content-Type',{'html':'text/html','js':'text/javascript','css':'text/css'}[name.rsplit('.',1)[1]]+'; charset=utf-8');self.end_headers();self.wfile.write(body);return
            return super().do_GET()
    ThreadingHTTPServer.request_queue_size=128
    server = ThreadingHTTPServer(('127.0.0.1',0), partial(Handler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with socket.socket() as probe: probe.bind(('127.0.0.1',0)); debug=probe.getsockname()[1]
    child=subprocess.Popen([r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe','--headless=new','--disable-gpu','--no-first-run',f'--user-data-dir={root / "edge"}',f'--remote-debugging-port={debug}','about:blank'],creationflags=0x08000000,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    browser_process=psutil.Process(child.pid)
    browser_process.create_time()
    try:
        tabs=wait_for(lambda:json.loads(read_http(f'http://127.0.0.1:{debug}/json/list')),timeout=30)
        c=CDP(next(tab for tab in tabs if tab.get('type')=='page')['webSocketDebuggerUrl'])
        c.call('Page.enable')
        c.call('Page.addScriptToEvaluateOnNewDocument',source="""window.uiErrors=[];addEventListener('error',e=>uiErrors.push(e.message));Object.defineProperties(HTMLMediaElement.prototype,{readyState:{get:()=>2},duration:{get:()=>2400},currentTime:{get(){return this._time||0},set(v){this._time=v;this.dispatchEvent(new Event('timeupdate'))}}});HTMLMediaElement.prototype.load=function(){};""")
        c.call('Emulation.setDeviceMetricsOverride',width=1920,height=1080,deviceScaleFactor=1,mobile=False)
        c.call('Page.navigate',url=f'http://127.0.0.1:{server.server_port}/?job={identity}')
        def workspace_ready():
            try:return c.evaluate('!!document.querySelector("#recording-notes")?.options.length && !!document.querySelector("#report-editor")?.contentDocument?.querySelector("#personal-preview [data-note-time]")')
            except RuntimeError as error:
                if 'navigated' in str(error) or 'context' in str(error):return False
                raise
        try:
            wait_for(workspace_ready,timeout=35)
        except TimeoutError:
            print('Workspace diagnostics:',c.evaluate('({url:location.href,errors:window.uiErrors,ready:document.readyState,resources:performance.getEntriesByType("resource").map(x=>({name:x.name,size:x.transferSize,status:x.responseStatus})),tail:document.body.innerHTML.slice(-1800)})'),flush=True)
            raise
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
        if '--spacing-only' in sys.argv:
            measurements=evaluate("""(()=>{const rect=s=>document.querySelector(s).getBoundingClientRect(),gap=(a,b)=>rect(b).top-rect(a).bottom;const groups=document.querySelectorAll('.recording-notes-heading>.vd-control-group');return {notes:gap('#recording-notes','#open-recording-notes'),article:gap('#recording-article','#open-recording-article'),buttons:rect('#construction-article').left-rect('#open-recording-article').right,groups:groups[1].getBoundingClientRect().top-groups[0].getBoundingClientRect().bottom}})()""")
            assert measurements=={'notes':8,'article':8,'buttons':8,'groups':16},measurements
            evaluate('document.querySelector(".recording-notes-heading").scrollIntoView({block:"start"})')
            c.screenshot(out/'consistent-control-spacing.png')
            assert evaluate('window.uiErrors')==[]
            print('PASS: related field/action gaps 8 px, action button gaps 8 px, independent groups 16 px',flush=True)
            sys.exit(0)
        if '--recovery-only' in sys.argv:
            evaluate('[...document.querySelectorAll("button")].find(b=>b.textContent==="Исправить конспект вручную").click()')
            wait_for(lambda:evaluate('!!document.querySelector(".construction-recovery[open]")'))
            assert '2' in c.visible_text('[data-summary]')
            assert evaluate('document.querySelectorAll("[data-issues] li").length')==2
            c.click('[data-issues] li button')
            assert evaluate('(()=>{const t=document.querySelector(".construction-recovery textarea");return t.value.slice(t.selectionStart,t.selectionEnd)})()')=='00:00:05'
            c.screenshot(out/'recovery-diagnostics.png')
            c.call('Emulation.setDeviceMetricsOverride',width=760,height=560,deviceScaleFactor=1,mobile=False)
            assert evaluate('(()=>{const r=document.querySelector(".construction-recovery").getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.height<=innerHeight})()')
            c.screenshot(out/'recovery-diagnostics-760.png')
            c.call('Emulation.setDeviceMetricsOverride',width=1920,height=1080,deviceScaleFactor=1,mobile=False)
            c.click('[data-candidate="00:00:00"]')
            assert evaluate('document.querySelectorAll("[data-issues] li").length')==2
            assert 'ожидает проверки' in c.visible_text('[data-resolution]')
            assert 'Оглавление\n### [00:00:00]' in evaluate('document.querySelector(".construction-recovery textarea").value')
            c.click('[data-fix-all]')
            assert evaluate('document.querySelectorAll("[data-issues] li").length')==2
            assert evaluate('document.querySelector(".construction-recovery textarea").value.includes("00:00:05")') is False
            c.click('[data-check]')
            wait_for(lambda:'Проверка пройдена' in c.visible_text('[data-summary]'))
            assert not (failed/'construction-manual.json').exists()
            c.click('.construction-recovery [type=submit]')
            wait_for(lambda:not evaluate('!!document.querySelector(".construction-recovery[open]")'))
            assert (failed/'construction-result.md').read_text(encoding='utf-8')==raw
            assert '00:00:05' not in json.loads((failed/'construction-manual.json').read_text(encoding='utf-8'))['text']
            assert evaluate('window.uiErrors')==[]
            print('PASS: recovery lists all errors, selects exact occurrences, previews grounded replacements, validates without saving, preserves raw answer',flush=True)
            sys.exit(0)
        if '--independent-versions-only' in sys.argv:
            original = evaluate('document.querySelector("#recording-speech").value')
            assert not evaluate('[...document.querySelector("#recording-speech").options].some(item=>item.value==="notes-a")')
            evaluate("document.querySelector('#recording-article').value='/output/article-a/report.html';document.querySelector('#recording-article').dispatchEvent(new Event('change'))")
            wait_for(lambda: 'article-a/report.html' in evaluate('document.querySelector("#report-editor").src'))
            assert evaluate('document.querySelector("#recording-speech").value') == original
            evaluate("document.querySelector('#recording-notes').value='/output/notes-b/report.html';document.querySelector('#recording-notes').dispatchEvent(new Event('change'))")
            wait_for(lambda: 'notes-b/report.html' in evaluate('document.querySelector("#report-editor").src'))
            assert evaluate('document.querySelector("#recording-speech").value') == original
            evaluate("document.querySelector('#recording-speech').value='original';document.querySelector('#recording-speech').dispatchEvent(new Event('change'))")
            wait_for(lambda: evaluate('document.querySelector("#recording-speech").value') == 'original')
            assert 'notes-b/report.html' in evaluate('document.querySelector("#report-editor").src')
            evaluate('document.querySelector("#report-editor").contentDocument.querySelector(".CodeMirror").CodeMirror.replaceRange("Draft",{line:0,ch:0})')
            evaluate("document.querySelector('#recording-notes').value='/output/notes-a/report.html';document.querySelector('#recording-notes').dispatchEvent(new Event('change'))")
            assert 'notes-b/report.html' in evaluate('document.querySelector("#report-editor").src')
            assert evaluate('document.querySelector("#report-editor").contentWindow.notesEditorDirty()')
            assert evaluate('window.uiErrors') == []
            c.screenshot(out/'independent-versions.png')
            print('PASS: independent report/transcript selection and unsaved report guard',flush=True)
            sys.exit(0)
        if '--notes-menu-only' in sys.argv:
            assert evaluate('document.querySelector("#recording-original-response").closest("#recording-notes-actions")!==null')
            assert evaluate('!document.querySelector("#report-editor").contentDocument.querySelector("[data-notes-view=model]").checkVisibility()')
            assert evaluate('[...document.querySelector("#report-editor").contentDocument.querySelectorAll(".notes-toolbar button")].filter(x=>x.checkVisibility()).length')==2
            evaluate('document.querySelector("#report-editor").contentDocument.querySelector(".CodeMirror").CodeMirror.replaceRange(" Unsaved edit",{line:0,ch:0})')
            assert evaluate('document.querySelector("#report-editor").contentWindow.notesEditorDirty()')
            c.click('#recording-notes-actions>summary')
            c.click('#recording-original-response')
            assert evaluate('!document.querySelector("#report-editor").contentDocument.querySelector("#model-material").hidden')
            assert evaluate('document.querySelector("#report-editor").contentWindow.notesEditorDirty()')
            assert not evaluate('document.querySelector("#recording-notes-actions").open')
            assert 'Ваши правки сохраняются отдельно' in evaluate('document.querySelector("#report-editor").contentDocument.querySelector("#editor-status").textContent')
            evaluate('document.querySelector("#report-editor").contentDocument.querySelector("[data-notes-view=read]").click()')
            assert evaluate('!document.querySelector("#report-editor").contentDocument.querySelector("#personal-preview").hidden')
            assert 'Unsaved edit' in evaluate('document.querySelector("#report-editor").contentDocument.querySelector(".CodeMirror").CodeMirror.getValue()')
            assert evaluate('document.querySelector("#report-editor").contentWindow.notesEditorDirty()')
            c.screenshot(out/'notes-original-response-menu.png')
            assert evaluate('window.uiErrors')==[]
            print('PASS: model result moved into notes actions; read/edit remain; unsaved draft survives mode switches',flush=True)
            sys.exit(0)
        if '--article-only' in sys.argv:
            wait_for(lambda:not evaluate('document.querySelector("#construction-article").disabled'))
            wait_for(lambda:evaluate('!document.querySelector("#construction-model").disabled'))
            evaluate("window.articleCalls=[];window.originalFetch=window.fetch;window.fetch=(url,options)=>url==='/api/native/postprocess'?(articleCalls.push(JSON.parse(options.body)),new Promise(resolve=>{window.replyArticle=resolve})):originalFetch(url,options)")
            evaluate('window.originalEditing=speechReplyEditing;window.speechReplyEditing=()=>true')
            c.click('#construction-article')
            assert 'Сначала сохраните' in c.visible_text('#article-status')
            assert evaluate('articleCalls.length')==0
            evaluate('window.speechReplyEditing=originalEditing')
            c.click('#construction-article')
            assert evaluate('articleCalls.length')==0
            assert 'статьи' in c.visible_text('#construction-heading')
            evaluate('document.querySelector("#construction-article-prompt").value="Custom article instruction"')
            c.click('#construction-run')
            wait_for(lambda:evaluate('articleCalls.length===1'))
            payload=evaluate('articleCalls[0]')
            assert payload['task']=='notes' and payload['construction']['result_kind']=='article'
            assert payload['construction']['article_prompt']=='Custom article instruction'
            assert payload['translate_after'] is False and payload['construction']['model']=='model-a'
            assert evaluate('document.querySelector("#construction-article").disabled')
            assert evaluate('document.querySelector("#construction-article").getAttribute("aria-busy")==="true"')
            evaluate('document.querySelector("#construction-article").click()')
            assert evaluate('articleCalls.length')==1
            evaluate("replyArticle(new Response(JSON.stringify({error:'Эта запись уже находится в обработке'}),{status:409,headers:{'Content-Type':'application/json'}}))")
            wait_for(lambda:'уже находится' in c.visible_text('#article-status'))
            assert evaluate('document.querySelector("#article-status").classList.contains("vd-error")')
            assert not evaluate('document.querySelector("#construction-article").disabled')
            evaluate('window.constructionUI.openSettings("notes")')
            assert 'конспекта' in c.visible_text('#construction-heading')
            assert evaluate('document.querySelector("#construction-input").closest("label").hidden')
            assert evaluate('!document.querySelector("#construction-notes-instruction").hidden')
            evaluate('window.constructionUI.openSettings("article")')
            assert evaluate('document.querySelector("#construction-article-prompt").value')=='Custom article instruction'
            evaluate('document.querySelector("#construction-heading").scrollIntoView({block:"start"})')
            c.screenshot(out/'article-action.png')
            evaluate('window.constructionUI.select({folder:"notes-a",has_ready_transcript:true,running:false,job:{status:"running"}})')
            assert evaluate('document.querySelector("#construction-run").disabled')
            assert 'уже выполняется' in c.visible_text('#construction-run-reason')
            evaluate('window.constructionUI.select({folder:"notes-a",has_ready_transcript:true,running:false,job:{status:"queued"}})')
            assert 'в очереди' in c.visible_text('#construction-run-reason')
            evaluate('window.constructionUI.select({folder:"notes-a",has_ready_transcript:true,running:false,job:{status:"done"}})')
            assert not evaluate('document.querySelector("#construction-run").disabled')
            assert evaluate('document.querySelector("#construction-context").closest(".construction-context-field").contains(document.querySelector("#construction-auto-context"))')
            evaluate('window.constructionUI.openSettings("notes");document.querySelector("#construction-context").closest("details").open=true;document.querySelector("#construction-context").scrollIntoView({block:"center"})')
            c.screenshot(out/'notes-context.png')
            assert evaluate('window.uiErrors')==[]
            print('PASS: article action sends chosen model, full-transcript result kind, no translation; dirty/busy/error guards preserved',flush=True)
            sys.exit(0)
        if '--toolbar-only' in sys.argv:
            assert evaluate('document.querySelector("#recording-translate").closest("#translation-settings-panel")!==null')
            assert evaluate('document.querySelector("#transcript-disclosure").open')
            evaluate('document.querySelector("#transcript-disclosure").open=false')
            assert evaluate('!document.querySelector("#speech-feed").checkVisibility()')
            evaluate('document.querySelector("#transcript-disclosure").open=true')
            assert evaluate('document.querySelector("#report-editor").contentDocument.querySelector(".note-time").textContent==="00:00:00"')
            print('Notes font:',evaluate('(()=>{const d=document.querySelector("#report-editor").contentDocument;return {html:d.defaultView.getComputedStyle(d.documentElement).fontFamily,body:d.defaultView.getComputedStyle(d.body).fontFamily}})()'),flush=True)
            dimensions=evaluate('(()=>{const f=document.querySelector("#report-editor"),d=f.contentDocument,p=d.querySelector("#personal-preview");return {frame:f.clientHeight,body:d.body.scrollHeight,width:d.body.clientWidth,viewport:d.documentElement.clientWidth,overflow:p.scrollHeight-p.clientHeight}})()')
            assert abs(dimensions['width']-dimensions['viewport'])<3,dimensions
            assert evaluate('getComputedStyle(document.querySelector("#report-editor")).resize==="vertical"')
            before=evaluate('document.querySelector("#report-editor").clientHeight')
            evaluate('document.querySelector("#report-editor").style.height="1000px"')
            assert evaluate('document.querySelector("#report-editor").clientHeight')>before
            evaluate('document.querySelector("#report-editor").style.height=""')
            evaluate('document.querySelector("#speech-feed").scrollIntoView({block:"center"})')
            geometry=evaluate("""(()=>{const nodes=['#subtitle-mode','#toggle-speaker-names','#download-srt','.subtitle-history button'].map(s=>document.querySelector(s));return nodes.map(n=>{const r=n.getBoundingClientRect();return {bottom:r.bottom,top:r.top,height:r.height}})})()""")
            assert abs(geometry[0]['bottom']-geometry[1]['bottom'])<2, geometry
            assert geometry[2]['top']>=geometry[0]['top'], geometry
            assert all(30<=x['height']<=34 for x in geometry), geometry
            evaluate('document.querySelector("#stage-notes").scrollIntoView({block:"start"})')
            c.screenshot(out/'notes-layout.png')
            evaluate('document.querySelector("#speech-feed").scrollIntoView({block:"center"})')
            c.screenshot(out/'transcript-toolbar.png')
            for width in (1100,760,360):
                c.call('Emulation.setDeviceMetricsOverride',width=width,height=900,deviceScaleFactor=1,mobile=False)
                assert evaluate('document.documentElement.scrollWidth<=innerWidth'), width
            assert evaluate('window.uiErrors')==[]
            print('PASS: toolbar controls aligned and compact; grouped exports wrap; 1920/1100/760/360 fit',flush=True)
            sys.exit(0)
        if '--job-errors-only' in sys.argv:
            fixture_job=json.loads((job_folder/'job.json').read_text(encoding='utf-8'))
            fixture_job.update(status='error',stage='notes',error='См. журнал',cancelled=False)
            write_json(root/'output/notes-a/construction-error.json',{'error':'Нужны заголовки с таймкодами'})
            (root/'output/notes-a/construction-result.md').write_text('Saved model answer',encoding='utf-8')
            write_json(job_folder/'job.json',fixture_job)
            evaluate('recordingSelection.refresh()')
            wait_for(lambda:'Нужны заголовки' in c.visible_text('#recording-job-error'))
            assert c.visible_text('#run-state')=='Ошибка'
            assert not evaluate('document.querySelector("#recording-job-error").hidden')
            assert not evaluate('document.querySelector("#recording-retry").hidden')
            assert 'сохранённым ответом' in c.visible_text('#recording-retry')
            assert not evaluate('document.querySelector("#recording-job-error").closest("details")')
            evaluate('window.originalEditing=speechReplyEditing;window.speechReplyEditing=()=>true')
            c.click('#recording-retry')
            assert 'Сначала сохраните' in c.visible_text('#recording-job-error')
            evaluate('window.speechReplyEditing=originalEditing')
            fixture_job.update(cancelled=True,error='По вашей команде')
            write_json(job_folder/'job.json',fixture_job)
            evaluate('recordingSelection.refresh()')
            wait_for(lambda:'Обработка остановлена' in c.visible_text('#recording-job-error'))
            assert c.visible_text('#run-state')=='Остановлено'
            assert 'Нужны заголовки' not in c.visible_text('#recording-job-error')
            fixture_job.update(status='done',cancelled=False,error=None)
            write_json(job_folder/'job.json',fixture_job)
            evaluate('recordingSelection.refresh()')
            wait_for(lambda:evaluate('document.querySelector("#recording-job-error").hidden && document.querySelector("#recording-retry").hidden'))
            assert evaluate('window.uiErrors')==[]
            print('PASS: actual API error alert outside disclosure, structured reason, explicit cached retry with dirty guard, error/cancel badges, success clears alert',flush=True)
            sys.exit(0)
        if '--models-only' in sys.argv:
            c.fill('#recording-notes','__new__')
            wait_for(lambda:evaluate('document.querySelector("#construction-model").tagName==="SELECT" && document.querySelector("#construction-model").options.length>=4'))
            c.fill('#construction-model','gpt-oss:20b')
            assert not evaluate('document.querySelector("#construction-run").disabled')
            c.click('#construction-load-models')
            wait_for(lambda:not evaluate('document.querySelector("#construction-load-models").disabled'))
            assert evaluate('document.querySelector("#construction-model").value')=='gpt-oss:20b'
            c.fill('#construction-provider','gemini')
            wait_for(lambda:evaluate('[...document.querySelector("#construction-model").options].some(o=>o.value==="gemini-test")'))
            c.fill('#construction-model','gemini-test')
            c.fill('#construction-provider','ollama')
            wait_for(lambda:evaluate('document.querySelector("#construction-model").value==="gpt-oss:20b" && !document.querySelector("#construction-load-models").disabled'))
            evaluate("window.modelsFetch=fetch;window.fetch=(url,options)=>String(url).startsWith('/api/construction-models')?Promise.resolve(new Response(JSON.stringify({error:'Сервер недоступен'}),{status:503})):modelsFetch(url,options)")
            c.click('#construction-load-models')
            wait_for(lambda:'Сервер недоступен' in c.visible_text('#construction-model-status'))
            assert evaluate('document.querySelector("#construction-run").disabled')
            evaluate('window.fetch=modelsFetch')
            c.click('#construction-load-models')
            wait_for(lambda:not evaluate('document.querySelector("#construction-run").disabled'))
            evaluate('document.querySelector("#construction-model").append(new Option("missing-model","missing-model"));document.querySelector("#construction-model").value="missing-model"')
            c.click('#construction-load-models')
            wait_for(lambda:'Прежняя модель недоступна' in c.visible_text('#construction-model-status'))
            assert evaluate('document.querySelector("#construction-model").value==="missing-model" && document.querySelector("#construction-run").disabled')
            c.fill('#construction-model','qwen3.5:9b')
            wait_for(lambda:not evaluate('document.querySelector("#construction-run").disabled'))
            evaluate('document.querySelector("#construction-panel").scrollIntoView({block:"start"})')
            c.screenshot(out/'model-picker.png')
            assert evaluate('window.uiErrors')==[]
            print('PASS: automatic model select, refresh preserves choice, provider isolation, network error/retry, missing model blocked',flush=True)
            sys.exit(0)
        if '--diarization-progress-only' in sys.argv:
            fixture=live.snapshot(root,root/'output/notes-a')
            evaluate('window.progressFixture='+json.dumps(fixture,ensure_ascii=False))
            def show_progress(value, status='running'):
                return evaluate('''(()=>{const value='''+json.dumps(value,ensure_ascii=False)+''';document.dispatchEvent(new CustomEvent('recording-snapshot',{detail:{snapshot:{...progressFixture,diarization_progress:value},job:{id:"fixture",task:"diarize",status:'''+json.dumps(status)+'''}}}));const node=document.querySelector('#diarization-progress'),ring=node.querySelector('[role=progressbar]');return {hidden:node.hidden,indeterminate:ring.classList.contains('indeterminate'),percent:ring.getAttribute('aria-valuenow'),offset:ring.querySelector('.diarization-ring-value').getAttribute('stroke-dashoffset'),text:node.textContent,barHidden:document.querySelector('#stage-progress').hidden}})()''')
            stamp=time.time()
            result=show_progress({'stage':'model_load','label':'Загружаем локальную модель','updated_at':stamp,'stage_started_at':stamp})
            assert not result['hidden'] and result['indeterminate'] and result['percent'] is None and result['barHidden']
            result=show_progress({'stage':'embeddings','label':'Сравниваем голоса','completed':3,'total':10,'updated_at':stamp,'stage_started_at':stamp})
            assert not result['indeterminate'] and result['percent']=='30' and result['offset']=='70'
            assert '30%' in result['text'] and '3 из 10' in result['text']
            result=show_progress({'stage':'clustering','label':'Объединяем одинаковые голоса','updated_at':stamp-70,'stage_started_at':stamp-80})
            assert result['indeterminate'] and result['percent'] is None and 'Новых данных' in result['text']
            c.screenshot(out/'diarization-progress.png')
            result=show_progress({'stage':'complete','label':'Готово'},'done')
            assert result['hidden'] and not result['barHidden']
            result=show_progress({'stage':'embeddings','label':'Сравниваем голоса','completed':3,'total':0})
            assert result['indeterminate'] and result['percent'] is None
            assert show_progress({},'error')['hidden']
            assert evaluate('window.uiErrors')==[]
            print('PASS: current stage only; spinner; measured 30% ring; stale event age; unknown total; completion/error hide progress',flush=True)
            sys.exit(0)
        if '--speakers-only' in sys.argv:
            evaluate("""window.postCalls=0;window.originalFetch=window.fetch;window.fetch=(url,options)=>url==='/api/native/postprocess'?(postCalls++,new Promise(resolve=>{window.replyPost=resolve})):originalFetch(url,options)""")
            c.click('#recording-diarize')
            assert evaluate('document.querySelector("#recording-diarize").disabled && document.querySelector("#recording-diarize").getAttribute("aria-busy")==="true"')
            assert 'Запускаем' in c.visible_text('#recording-action-status')
            evaluate('document.querySelector("#recording-diarize").click()')
            assert evaluate('postCalls')==1
            evaluate("replyPost(new Response(JSON.stringify({error:'Дождитесь завершения обработки или настройки'}),{status:409,headers:{'Content-Type':'application/json'}}))")
            wait_for(lambda:'Не удалось запустить' in c.visible_text('#recording-action-status'))
            assert evaluate('document.querySelector("#recording-action-status").classList.contains("vd-error")')
            assert not evaluate('document.querySelector("#recording-diarize").disabled')
            evaluate('window.fetch=originalFetch')
            def saved_rows():
                return json.loads((root/'output/notes-a/transcript-edits.json').read_text(encoding='utf-8'))
            assert not evaluate('!!document.querySelector("#speech-feed .speaker-name")')
            assert evaluate('getComputedStyle(document.querySelector("#speech-feed .speaker-select")).minHeight')=='32px'
            c.click('#toggle-speaker-names')
            wait_for(lambda:evaluate('!!document.querySelector("#speaker-names input")'))
            c.fill('#speaker-names input','Алекс')
            c.click('#speaker-names-form button')
            wait_for(lambda:'Алекс' in c.visible_text('#speech-feed .speaker-select'))
            assert evaluate('[...document.querySelectorAll("#speech-feed .speaker-select")].every(s=>s.selectedOptions[0].textContent==="Алекс")')
            assert evaluate('document.querySelector("#speech-feed .speaker-select").getBoundingClientRect().width < 100'), 'Speaker arrow is detached from its short name'
            c.click('#toggle-speaker-names')
            c.fill('#speech-feed .speaker-select','__new_speaker__')
            wait_for(lambda:evaluate('!document.querySelector("#speech-feed .speaker-name-input").hidden'))
            c.fill('#speech-feed .speaker-name-input','Мария')
            c.call('Input.dispatchKeyEvent',type='keyDown',key='Enter',windowsVirtualKeyCode=13)
            c.call('Input.dispatchKeyEvent',type='keyUp',key='Enter',windowsVirtualKeyCode=13)
            wait_for(lambda:(root/'output/notes-a/transcript-edits.json').exists())
            assert saved_rows()['segments'][0]['speaker']!='speaker_1'
            assert saved_rows()['segments'][1]['speaker']=='speaker_1'
            assert saved_rows()['segments'][0]['text']=='Реплика 0. Проверка синхронизации и правок.'
            assert saved_rows()['segments'][0]['start']==0 and saved_rows()['segments'][0]['end']==30
            assert saved_rows()['translations']['s0']=='Сохранённый перевод'
            wait_for(lambda:'Мария' in c.visible_text('#speech-feed .speaker-select'))
            c.fill('#speech-feed .speaker-select','unknown')
            wait_for(lambda:saved_rows()['segments'][0]['speaker']=='unknown')
            c.fill('#speech-feed .speaker-select','__new_speaker__')
            c.fill('#speech-feed .speaker-name-input','Не сохранять')
            c.call('Input.dispatchKeyEvent',type='keyDown',key='Escape',windowsVirtualKeyCode=27)
            c.call('Input.dispatchKeyEvent',type='keyUp',key='Escape',windowsVirtualKeyCode=27)
            assert evaluate('document.querySelector("#speech-feed .speaker-name-input").hidden')
            evaluate('document.querySelector("#speech-feed").scrollIntoView({block:"center"});document.activeElement.blur()')
            c.screenshot(out/'speakers-full.png')
            for width in (1100,760,360):
                c.call('Emulation.setDeviceMetricsOverride',width=width,height=900,deviceScaleFactor=1,mobile=False)
                assert evaluate('document.documentElement.scrollWidth<=innerWidth'), width
            c.screenshot(out/'speakers-narrow.png')
            assert evaluate('window.uiErrors')==[]
            print('PASS: global rename; create and assign one reply; reassignment; Escape; text, times and translation preserved; 1920/1100/760/360 layouts',flush=True)
            sys.exit(0)
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
        wait_for(lambda:evaluate('[...document.querySelector("#construction-model").options].some(o=>o.value==="gemini-test")'))
        c.fill('#construction-model','gemini-test')
        wait_for(lambda:evaluate('!document.querySelector("#construction-run").disabled'),timeout=8)
        c.click('#construction-run')
        wait_for(lambda:'Подтвердите отправку' in c.visible_text('#construction-status'),timeout=5)
        c.click('#cancel-new-notes')
        c.fill('#recording-speech','__new__')
        assert evaluate('document.querySelector("#speech-settings").open')
        evaluate('document.querySelector("#speech-settings").open=false;scrollTo(0,0)')
        def frame_eval(expression):
            return evaluate('(()=>{const doc=document.querySelector("#report-editor").contentDocument;return '+expression+'})()')
        def frame_click(selector):
            point=evaluate('''(()=>{const frame=document.querySelector('#report-editor'),e=frame.contentDocument.querySelector('''+json.dumps(selector)+''');e.scrollIntoView({block:'center'});frame.scrollIntoView({block:'center'});const r=e.getBoundingClientRect(),f=frame.getBoundingClientRect();return [f.x+r.x+r.width/2,f.y+r.y+r.height/2]})()''')
            for kind in ('mousePressed','mouseReleased'):c.call('Input.dispatchMouseEvent',type=kind,x=point[0],y=point[1],button='left',clickCount=1)
        def frame_fill(selector,value):
            evaluate('(()=>{const e=document.querySelector("#report-editor").contentDocument.querySelector('+json.dumps(selector)+');e.value='+json.dumps(value)+';e.dispatchEvent(new Event("input",{bubbles:true}));})()')
        def key(name,modifiers=0):
            for kind in ('keyDown','keyUp'):c.call('Input.dispatchKeyEvent',type=kind,key=name,modifiers=modifiers,windowsVirtualKeyCode={'Escape':27,'Enter':13,'z':90}.get(name,0))
        wait_for(lambda:frame_eval('!!doc.querySelector(".CodeMirror")'))
        initial_notes=frame_eval('doc.querySelector(".CodeMirror").CodeMirror.getValue()')
        frame_click('#add-section');frame_click('.notes-section-editor [data-cancel]')
        assert frame_eval('doc.querySelector(".CodeMirror").CodeMirror.getValue()')==initial_notes
        frame_click('#add-section');key('Escape')
        wait_for(lambda:frame_eval('!doc.querySelector(".notes-section-editor")'),timeout=5)
        assert frame_eval('doc.querySelector(".CodeMirror").CodeMirror.getValue()')==initial_notes
        frame_click('#add-section');frame_fill('.notes-section-editor [name=heading]','[00:03:00] Новый раздел');frame_fill('.notes-section-editor [name=body]','Уникальная правка раздела')
        frame_click('.notes-section-editor [type=submit]')
        assert 'Уникальная правка раздела' in frame_eval('doc.querySelector(".CodeMirror").CodeMirror.getValue()')
        key('z',2)
        assert frame_eval('doc.querySelector(".CodeMirror").CodeMirror.getValue()')==initial_notes
        key('z',10)
        assert 'Уникальная правка раздела' in frame_eval('doc.querySelector(".CodeMirror").CodeMirror.getValue()')
        frame_click('#reset-notes');frame_click('[data-discard]')
        wait_for(lambda:frame_eval('doc.querySelector(".CodeMirror").CodeMirror.getValue()')==initial_notes,timeout=5)
        # Section Ctrl-hover invokes the same local draft dialog without saving to disk.
        point=evaluate('''(()=>{const f=document.querySelector('#report-editor'),e=f.contentDocument.querySelector('#personal-preview h2');e.scrollIntoView({block:'center'});f.scrollIntoView({block:'center'});const r=e.getBoundingClientRect(),p=f.getBoundingClientRect();return [p.x+r.x+100,p.y+r.y+r.height/2]})()''')
        c.call('Input.dispatchMouseEvent',type='mouseMoved',x=1,y=1)
        c.call('Input.dispatchMouseEvent',type='mouseMoved',x=point[0],y=point[1],modifiers=2)
        assert frame_eval('!!doc.querySelector(".notes-section-editor")')
        frame_fill('.notes-section-editor [name=body]','Локальная правка');frame_click('.notes-section-editor [data-cancel]')
        assert frame_eval('doc.querySelector(".CodeMirror").CodeMirror.getValue()')==initial_notes
        def quick_open():
            point=evaluate('''(()=>{const p=document.querySelector('#speech-feed .utterance .subtitle-original');p.scrollIntoView({block:'center'});const r=p.getBoundingClientRect();return [r.x+10,r.y+r.height/2]})()''')
            c.call('Input.dispatchMouseEvent',type='mouseMoved',x=1,y=1)
            c.call('Input.dispatchMouseEvent',type='mouseMoved',x=point[0],y=point[1],modifiers=2)
            wait_for(lambda:evaluate('!!document.querySelector(".quick-reply-editor textarea")'),timeout=5)
        quick_open()
        initial_input=evaluate('document.querySelector(".quick-reply-editor textarea").value')
        c.call('Input.insertText',text=' Временный ввод')
        key('z',2)
        assert evaluate('document.querySelector(".quick-reply-editor textarea").value')==initial_input
        c.fill('.quick-reply-editor textarea','Исправлено через Ctrl')
        evaluate('recordingSelection.refresh()')
        assert evaluate('document.querySelector(".quick-reply-editor textarea").value')=='Исправлено через Ctrl'
        c.call('Input.dispatchKeyEvent',type='keyDown',key='Enter',code='Enter',windowsVirtualKeyCode=13,modifiers=2)
        c.call('Input.dispatchKeyEvent',type='keyUp',key='Enter',code='Enter',windowsVirtualKeyCode=13)
        wait_for(lambda:evaluate('!document.querySelector(".quick-reply-editor")'),timeout=5)
        edits=json.loads((root/'output/notes-b/transcript-edits.json').read_text(encoding='utf-8'))
        assert edits['segments'][0]['text']=='Исправлено через Ctrl'
        assert edits['segments'][0]['speaker']=='speaker_1'
        assert edits['translations']['s0']=='Сохранённый перевод'
        c.click('#speech-feed .subtitle-original')
        c.call('Input.dispatchKeyEvent',type='keyDown',key='Control',windowsVirtualKeyCode=17,modifiers=2)
        wait_for(lambda:evaluate('!!document.querySelector(".quick-reply-editor")'),timeout=5)
        key('z',2)
        c.call('Input.dispatchKeyEvent',type='keyUp',key='Control',windowsVirtualKeyCode=17)
        wait_for(lambda:json.loads((root/'output/notes-b/transcript-edits.json').read_text(encoding='utf-8'))['segments'][0]['text'].startswith('Реплика 0'),timeout=6)
        c.click('#speech-feed .subtitle-original');key('z',10)
        wait_for(lambda:json.loads((root/'output/notes-b/transcript-edits.json').read_text(encoding='utf-8'))['segments'][0]['text']=='Исправлено через Ctrl',timeout=6)
        quick_open();c.fill('.quick-reply-editor textarea','Несохранённый текст')
        c.fill('#recording-speech','original')
        wait_for(lambda:evaluate('!!document.querySelector("[data-keep-editing]")'))
        c.click('[data-keep-editing]')
        assert evaluate('document.querySelector(".quick-reply-editor textarea").value')=='Несохранённый текст'
        edits['segments'][0]['text']='Изменено в другой вкладке'
        write_json(root/'output/notes-b/transcript-edits.json',edits)
        c.click('.quick-reply-editor button')
        wait_for(lambda:'изменились' in c.visible_text('.quick-reply-editor [role=status]'))
        assert evaluate('document.querySelector(".quick-reply-editor textarea").value')=='Несохранённый текст'
        c.click('.quick-reply-editor textarea')
        c.call('Input.dispatchKeyEvent',type='keyDown',key='Escape',code='Escape',windowsVirtualKeyCode=27)
        c.call('Input.dispatchKeyEvent',type='keyUp',key='Escape',code='Escape',windowsVirtualKeyCode=27)
        evaluate('recordingSelection.refresh()')
        assert not evaluate('!!document.querySelector("#speech-feed .speaker-name")')
        c.click('#toggle-speaker-names')
        wait_for(lambda:evaluate('!!document.querySelector("#speaker-names input")'))
        c.fill('#speaker-names input','Новое имя')
        c.click('#speaker-names-form button')
        wait_for(lambda:'Новое имя' in c.visible_text('#speech-feed .speaker-select'),timeout=8)
        assert evaluate('[...document.querySelectorAll("#speech-feed .speaker-select")].every(s=>s.selectedOptions[0].textContent==="Новое имя")')
        c.click('#toggle-speaker-names')
        c.fill('#speech-feed .speaker-select','__new_speaker__')
        c.fill('#speech-feed .speaker-name-input','Мария')
        key('Enter')
        wait_for(lambda:json.loads((root/'output/notes-b/transcript-edits.json').read_text(encoding='utf-8'))['segments'][0]['speaker']!='speaker_1')
        edits=json.loads((root/'output/notes-b/transcript-edits.json').read_text(encoding='utf-8'))
        assert edits['segments'][1]['speaker']=='speaker_1'
        assert edits['segments'][0]['text']=='Изменено в другой вкладке'
        assert edits['translations']['s0']=='Сохранённый перевод'
        c.fill('#speech-feed .speaker-select','unknown')
        wait_for(lambda:json.loads((root/'output/notes-b/transcript-edits.json').read_text(encoding='utf-8'))['segments'][0]['speaker']=='unknown')
        evaluate('recordingSelection.refresh();scrollTo(0,0)')
        c.screenshot(out/'full-hd.png')
        for width in (1100,760,360):
            c.call('Emulation.setDeviceMetricsOverride',width=width,height=900,deviceScaleFactor=1,mobile=False)
            assert evaluate('document.documentElement.scrollWidth<=innerWidth'), width
        c.screenshot(out/'narrow.png')
        assert evaluate('window.uiErrors')==[], evaluate('window.uiErrors')
        evidence={'status':'PASS','scope':'Isolated Edge, real production HTML/JS, temporary speech/report artifacts, mocked native health and media metadata; no inference or user data', 'checks':['native job URL opens unified workspace directly','one shared player; embedded report has no media source','side layout: speech under video, notes right','expanded layout','player identity and time preserved across report variants','speech and Markdown heading synchronization','manual scroll pause and resume','magnet off','dirty report blocks variant switch','new notes settings preserve existing report','Google generation requires consent before submission','new speech settings','1920/1100/760/360 widths fit','no browser runtime errors']}
        evidence['checks']+=['Ctrl hover opens quick editor','polling preserves input','Ctrl+Enter saves text and preserves speaker/translation','dirty speech blocks version navigation','stale revision preserves input','Escape cancels','global rename, create-and-assign only one reply, reassignment']
        evidence['checks']+=['notes new section Cancel/Escape','notes applied section is one undo step','notes redo and reset to last saved','notes Ctrl-hover local edit cancel','subtitle Ctrl+Z and Ctrl+Shift+Z persist undo/redo']
        (out/'result.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(evidence,ensure_ascii=False))
    finally:
        # Only the isolated browser tree launched above, never the user's Edge.
        if child.poll() is None and browser_process.is_running():
            subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                           creationflags=0x08000000, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=20, check=False)
        try:
            targets=[*browser_process.children(recursive=True),browser_process]
        except psutil.NoSuchProcess:
            targets=[]
        for process in targets:
            try: process.terminate()
            except psutil.NoSuchProcess: pass
        _,alive=psutil.wait_procs(targets,timeout=10)
        for process in alive:
            try: process.kill()
            except psutil.NoSuchProcess: pass
        psutil.wait_procs(alive,timeout=5)
        child.wait(timeout=15);server.shutdown();server.server_close()
