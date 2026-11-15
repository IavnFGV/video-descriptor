"""Browser checks for native speech-form retirement; never starts recognition."""


def run(c, wait_for, out, web=False):
    wait_for(lambda: c.evaluate('!!document.querySelector("#recording-speech")?.options.length'))
    assert not c.evaluate('document.querySelector("#workspace-view-menu [data-panel=technical]")')
    if web:
        assert c.evaluate('window.recordingUI.native===false')
        assert c.evaluate('document.querySelector("#speech-engine").options.length>1')
        c.evaluate('document.querySelector("#recording-speech").value="__new__";document.querySelector("#recording-speech").dispatchEvent(new Event("change"))')
        assert c.evaluate('document.querySelector("#speech-settings").checkVisibility()')
        assert c.evaluate('document.querySelector("#speech-settings").contains(document.querySelector("#rerun-speech"))')
        assert c.evaluate('document.activeElement.id==="speech-engine"')
        assert c.evaluate('window.uiErrors.length===0'), c.evaluate('window.uiErrors')
        print('PASS: shared web keeps the engine picker and new-transcript form', flush=True)
        return

    wait_for(lambda: c.evaluate('window.recordingUI.native && !document.querySelector("#rerun-speech").disabled'))
    assert c.evaluate('document.querySelector("#recording-speech-settings").hidden')
    assert c.evaluate('!document.querySelector("#speech-settings").checkVisibility()')
    assert c.evaluate('document.querySelector("#speech-engine").value==="whisper-local"')
    assert c.evaluate('!document.querySelector("#rerun-speech").checkVisibility()')
    assert c.evaluate('!!document.querySelector("#recording-speech option[value=__new__]")')
    c.evaluate('window.workspaceView.setPanel("technical",true)')
    assert c.evaluate('!document.querySelector("#speech-settings").checkVisibility()')
    c.evaluate('window.workspaceView.setPanel("technical",false)')
    c.evaluate('''window.speechRequests=[];window.originalFetch=window.fetch;
      window.fetch=async function(url,options){
        if(String(url)==='/api/speech-run'){
          window.speechRequests.push(JSON.parse(options.body));
          throw new Error('Проверочный отказ без запуска обработки');
        }
        return window.originalFetch.apply(this,arguments);
      };
      window.savedPreferences=localStorage.getItem('video-descriptor:ui:workspace');
      window.originalSpeechEditing=window.speechReplyEditing;
      window.speechReplyEditing=()=>true;''')
    c.fill('#recording-speech', '__new__')
    assert c.evaluate('window.speechRequests.length===0')
    assert c.evaluate('document.querySelector("#speech-settings-status").textContent.includes("Завершите") || document.querySelector("#speech-settings-status").textContent.includes("завершите")')
    c.evaluate('window.speechReplyEditing=window.originalSpeechEditing')
    c.fill('#recording-speech', '__new__')
    wait_for(lambda: c.evaluate('document.querySelector("#speech-settings-status").textContent.includes("Проверочный отказ")'))
    assert c.evaluate('window.speechRequests.length===1')
    assert c.evaluate('window.speechRequests[0].engine==="whisper-local" && window.speechRequests[0].speech_only===true && !!window.speechRequests[0].video')
    assert c.evaluate('document.querySelector("#speech-settings-status").checkVisibility()')
    assert c.evaluate('!document.querySelector("#rerun-speech").disabled')
    assert c.evaluate('localStorage.getItem("video-descriptor:ui:workspace")===window.savedPreferences')
    assert c.evaluate('document.documentElement.dataset.viewTechnical==="false"')
    assert c.evaluate('document.querySelectorAll("#process-video").length===1 && document.querySelectorAll("#report-editor").length===1')
    for width in [1200, 760]:
        c.call('Emulation.setDeviceMetricsOverride', width=width, height=900, deviceScaleFactor=1, mobile=False)
        assert c.evaluate('!document.querySelector("#rerun-speech").checkVisibility()')
        assert c.evaluate('!document.querySelector("#speech-settings").checkVisibility()')
        assert c.evaluate('document.querySelector("#recording-speech").getBoundingClientRect().width>=200')
        assert c.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
    c.screenshot(out / 'speech-settings-retired.png')
    assert c.evaluate('window.uiErrors.length===0'), c.evaluate('window.uiErrors')
    print('PASS: native form hidden with technical on/off; dropdown creation, dirty guard, request payload, visible failure, unchanged preferences, responsive layout; no recognition', flush=True)
