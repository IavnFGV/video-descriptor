"""Processing-tab browser checks with recorded fixture requests; no model calls."""
import hashlib
import json


def run(c, wait_for, root, out, identity):
    evaluate = c.evaluate
    artifacts = list((root / 'output/notes-a/requests').rglob('*'))
    originals = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in artifacts if path.is_file()}
    wait_for(lambda: evaluate('document.querySelector("#recording-open-log").checkVisibility()'))
    assert evaluate('document.querySelector("#recording-job-error").textContent.includes("Fixture processing failure")')
    assert not evaluate('document.querySelector("#diagnostics").checkVisibility()')
    evaluate('''workspaceView.reset();window.processingFixture={player:document.querySelector('#process-video'),
      frame:document.querySelector('#report-editor'),log:document.querySelector('#log-feed'),
      url:location.href,history:history.length,storage:localStorage.getItem('video-descriptor:ui:workspace')};
      window.processingMutations=[];window.processingFetch=fetch;
      window.fetch=(url,options)=>{if(options?.method && options.method!=='GET')processingMutations.push(String(url));return processingFetch(url,options)}''')
    c.click('#recording-open-log')
    assert evaluate('document.documentElement.dataset.workspaceTab==="processing"')
    assert evaluate('document.querySelector("#processing-log").open && document.activeElement===document.querySelector("#processing-log summary")')
    assert evaluate('document.querySelector("#log-feed").textContent.includes("Fixture processing journal")')
    assert evaluate('document.querySelector("#recording-job-error").checkVisibility() && document.querySelector("#recording-retry").checkVisibility()')
    assert evaluate('!document.querySelector("#recording-processing").checkVisibility() && !document.querySelector("#recording-processing summary")')
    assert not evaluate('document.querySelector("#processing-overview")')
    assert not evaluate('[...document.querySelectorAll("#recording-processing-tab h3")].some(node=>node.textContent==="Ход обработки")')
    assert evaluate('document.documentElement.dataset.viewTechnical==="false"')
    c.click('#request-panel > summary')
    wait_for(lambda: evaluate('document.querySelector("#request-feed").textContent.includes("Fixture instruction")'))
    c.click('#response-panel > summary')
    c.click('#thinking-panel > summary')
    assert evaluate('document.querySelector("#response-feed").textContent==="Fixture original response"')
    assert evaluate('document.querySelector("#thinking-feed").textContent==="Fixture original reasoning"')
    c.click('#workspace-tab-transcript')
    c.click('#workspace-tab-processing')
    assert evaluate('document.querySelector("#processing-log").open && document.querySelector("#request-panel").open')
    assert evaluate('processingFixture.log===document.querySelector("#log-feed") && processingFixture.frame===document.querySelector("#report-editor")')
    assert evaluate('''processingFixture.player===document.querySelector('#process-video') &&
      processingFixture.history===history.length && processingFixture.url===location.href &&
      processingFixture.storage===localStorage.getItem('video-descriptor:ui:workspace')''')
    # Stored requests remain readable without a link to the retired legacy editor.
    assert not evaluate('document.querySelector("#open-prompt-settings").checkVisibility()')
    assert not evaluate('''document.querySelector('a[href="#prompt-settings-panel"]')''')
    assert not evaluate('document.querySelector("#model-prompt").checkVisibility()')
    evaluate('workspaceView.reset()')
    c.click('#workspace-tab-transcript')
    c.call('Input.dispatchKeyEvent', type='keyDown', key='End', code='End', windowsVirtualKeyCode=35)
    assert evaluate('document.activeElement.id==="workspace-tab-processing"')
    for width, height in [(1440, 900), (1200, 820), (760, 560), (375, 820)]:
        c.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
        assert evaluate('document.documentElement.scrollWidth<=innerWidth+1'), width
        assert evaluate('document.querySelectorAll("#workspace-tabs [role=tab]").length===5')
        c.screenshot(out / f'processing-tab-{width}.png')
    assert evaluate('processingMutations') == []
    # A fixture-only running job keeps stop/progress outside the tab.
    path = root / 'output/jobs' / identity / 'job.json'
    job = json.loads(path.read_text(encoding='utf-8'));job['status']='running';job.pop('error',None)
    path.write_text(json.dumps(job), encoding='utf-8')
    wait_for(lambda: evaluate('document.querySelector("#recording-stop").checkVisibility() && document.querySelector("#recording-open-log").hidden'), timeout=20)
    assert evaluate('document.querySelector("#stage-progress").checkVisibility()')
    assert evaluate('document.querySelector("#run-message").textContent!==""')
    c.click('#workspace-tab-details')
    assert evaluate('document.querySelector("#recording-stop").checkVisibility() && document.querySelector("#stage-progress").checkVisibility()')
    job['status']='queued';path.write_text(json.dumps(job), encoding='utf-8')
    wait_for(lambda: evaluate('document.querySelector("#run-message").textContent.includes("Задание в очереди")'), timeout=20)
    # Empty processing sections do not expose stale request/response data.
    job['status']='done';path.write_text(json.dumps(job), encoding='utf-8')
    evaluate('window.processingEmptyReady=false;document.addEventListener("recording-snapshot",event=>{if(event.detail.snapshot.folder==="original")window.processingEmptyReady=true})')
    c.fill('#recording-speech', 'original')
    wait_for(lambda: evaluate('window.processingEmptyReady'))
    assert evaluate('document.querySelector("#run-message").textContent===""')
    c.click('#workspace-tab-processing')
    assert evaluate('["request-panel","thinking-panel","response-panel","processing-log"].every(id=>document.getElementById(id).hidden)')
    assert evaluate('document.querySelector(".processing-empty").checkVisibility()')
    assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
    # A failed job can have no recording snapshot or detailed journal yet.
    job.update(status='error', folder=None, error='Fixture failure before progress')
    path.write_text(json.dumps(job), encoding='utf-8')
    c.call('Page.navigate', url=evaluate('location.origin') + '/create?job=' + identity)
    wait_for(lambda: evaluate('document.querySelector("#recording-open-log")?.checkVisibility() && document.querySelector("#run-message").textContent.includes("Fixture failure before progress")'), timeout=35)
    c.click('#recording-open-log')
    assert evaluate('document.querySelector("#run-message").textContent.includes("Fixture failure before progress")')
    assert evaluate('document.querySelector(".processing-empty").checkVisibility() && document.activeElement===document.querySelector(".processing-empty")')
    assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
    assert originals == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in originals}
    print('PASS: processing tab, recorded request/response/reasoning/log, error navigation, empty data, stop/progress, keyboard, responsive layout, unchanged original responses and no processing requests', flush=True)
