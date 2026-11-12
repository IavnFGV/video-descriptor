"""Browser scenarios for verify-recording-ui.py --workspace-view-only (isolated fixture)."""
import json


def run(c, wait_for, out, root):
    evaluate = c.evaluate

    def visible(selector):
        return evaluate(f'document.querySelector({json.dumps(selector)}).checkVisibility()')

    def panel(key, checked):
        # Exercise the real native checkbox and its change handler, not just the API.
        evaluate('document.querySelector("#workspace-view-menu").open=true')
        selector = f'#workspace-view-menu [data-panel={key}]'
        if evaluate(f'document.querySelector({json.dumps(selector)}).checked') != checked:
            c.click(selector)
        evaluate('document.querySelector("#workspace-view-menu").open=false')

    def rect(selector):
        return evaluate(f'(()=>{{const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return {{x:r.x,y:r.y,w:r.width,h:r.height}}}})()')

    assert visible('#shared-player') and visible('#speech-feed')
    assert visible('#recording-diarize')
    # One command bar for all screens; sidebar contains navigation only.
    assert evaluate('!!document.querySelector(".desktop-menu-bar #workspace-view-menu")')
    assert not evaluate('!!document.querySelector(".vd-global-nav #workspace-view-menu")')
    for selector in ['#stage-notes', '#recording-translation-panel', '#source-details', '#diagnostics']:
        assert not visible(selector), selector
    video, speech = rect('#shared-player'), rect('#stage-speech')
    assert video['x'] < speech['x'] and abs(video['y'] - speech['y']) < 2
    # The panel opens next to the left rail and stays inside the viewport.
    evaluate('document.querySelector("#workspace-view-menu").open=true')
    wait_for(lambda: evaluate('document.querySelector(".workspace-view-content").checkVisibility()'))
    rail, popup = rect('.desktop-header'), rect('.workspace-view-content')
    assert popup['x'] >= rail['x'] and popup['y'] >= rail['y'], (rail, popup)
    assert popup['x'] + popup['w'] <= 1920 and popup['y'] + popup['h'] <= 1080
    c.screenshot(out / 'workspace-menu-open.png')
    evaluate('document.querySelector("#workspace-view-menu").open=false')
    c.screenshot(out / 'workspace-default.png')
    evaluate('window.originalPlayer=document.querySelector("#process-video");window.originalFeed=document.querySelector("#speech-feed");originalPlayer.currentTime=45')
    for key, selector in [('video', '#shared-player'), ('transcript', '#stage-speech'),
                          ('speakers', '#recording-diarize'), ('translation', '#recording-translation-panel'),
                          ('notes', '#stage-notes'), ('article', '#material-tab-article'),
                          ('technical', '#source-details')]:
        panel(key, True)
        assert visible(selector), key
        panel(key, False)
        assert not visible(selector), key
        panel(key, True)
    assert evaluate('originalPlayer===document.querySelector("#process-video") && originalFeed===document.querySelector("#speech-feed") && originalPlayer.currentTime===45')
    evaluate('document.querySelector("#workspace-view-menu").open=true')
    c.click('[name=workspace-layout][value=stacked]')
    assert evaluate('document.documentElement.dataset.workspaceLayout') == 'stacked', evaluate('localStorage.getItem("video-descriptor:ui:workspace")')
    evaluate('document.querySelector("#workspace-view-menu").open=false')
    video, speech = rect('#shared-player'), rect('#stage-speech')
    assert video['x'] == speech['x'] and speech['y'] >= video['y'] + video['h']
    evaluate('window.beforeWorkspaceReload=true')
    c.call('Page.reload')
    wait_for(lambda: evaluate('!window.beforeWorkspaceReload && !!document.querySelector("#speech-feed .utterance")'))
    assert evaluate('document.documentElement.dataset.workspaceLayout') == 'stacked'
    wait_for(lambda: visible('#stage-notes') and visible('#recording-translation-panel'))
    evaluate('workspaceView.setLayout("side")')
    for width in [1440, 1024, 760, 360]:
        c.call('Emulation.setDeviceMetricsOverride', width=width, height=900, deviceScaleFactor=1, mobile=False)
        assert evaluate('document.documentElement.scrollWidth<=innerWidth+1'), width
        if width <= 1000:
            assert rect('#stage-speech')['y'] >= rect('#shared-player')['y'] + rect('#shared-player')['h']
        c.screenshot(out / f'workspace-{width}.png')
    c.call('Emulation.setDeviceMetricsOverride', width=1440, height=900, deviceScaleFactor=1, mobile=False)
    # The narrow layout turns the rail into a row; the panel opens below the entry.
    c.call('Emulation.setDeviceMetricsOverride', width=360, height=760, deviceScaleFactor=1, mobile=False)
    evaluate('document.querySelector("#workspace-view-menu").open=true')
    wait_for(lambda: evaluate('document.querySelector(".workspace-view-content").checkVisibility()'))
    narrow = rect('.workspace-view-content')
    assert narrow['x'] >= 0 and narrow['x'] + narrow['w'] <= 360, narrow
    assert narrow['y'] >= 0 and narrow['y'] + narrow['h'] <= 760, narrow
    c.screenshot(out / 'workspace-menu-narrow.png')
    evaluate('document.querySelector("#workspace-view-menu").open=false')
    c.call('Emulation.setDeviceMetricsOverride', width=1440, height=900, deviceScaleFactor=1, mobile=False)
    panel('video', False)
    assert abs(rect('#stage-speech')['w'] - rect('.studio-layout')['w']) < 2
    panel('video', True)
    panel('transcript', False)
    assert abs(rect('#shared-player')['w'] - rect('.studio-layout')['w']) < 2
    panel('video', False)
    assert visible('#workspace-view-empty') and visible('#recording-speech')
    assert visible('#source-details'), 'Technical information must not depend on player visibility'
    c.click('#workspace-view-empty button')
    assert visible('#shared-player') and visible('#speech-feed') and not visible('#stage-notes')
    assert evaluate('document.documentElement.dataset.workspaceLayout') == 'side'
    evaluate('document.querySelector("#workspace-view-menu").open=true;document.querySelector("#workspace-view-menu input").focus()')
    c.call('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    assert evaluate('!document.querySelector("#workspace-view-menu").open && document.activeElement===document.querySelector("#workspace-view-menu summary")')

    # Real quick editor survives hide, reset and repeated live rendering. No save/discard.
    point = evaluate('(()=>{const p=document.querySelector("#speech-feed .subtitle-original");p.scrollIntoView({block:"center"});const r=p.getBoundingClientRect();return [r.x+10,r.y+r.height/2]})()')
    c.call('Input.dispatchMouseEvent', type='mouseMoved', x=1, y=1)
    c.call('Input.dispatchMouseEvent', type='mouseMoved', x=point[0], y=point[1], modifiers=2)
    wait_for(lambda: evaluate('!!document.querySelector(".quick-reply-editor textarea")'), timeout=10)
    c.fill('.quick-reply-editor textarea', 'Workspace unsaved transcript')
    evaluate('window.quickDraft=document.querySelector(".quick-reply-editor textarea")')
    panel('transcript', False)
    evaluate('workspaceView.reset()')
    assert evaluate('quickDraft===document.querySelector(".quick-reply-editor textarea") && quickDraft.value==="Workspace unsaved transcript" && speechReplyEditing()')
    c.click('.quick-reply-editor button:last-of-type')
    # Existing edit guard may ask for confirmation; keep this fixture isolated.
    evaluate('document.querySelector("dialog[open] .vd-actions button:last-of-type")?.click()')

    # Shared report editor: visibility never reloads the iframe or clears dirty/Undo state.
    panel('notes', True)
    wait_for(lambda: evaluate('!!document.querySelector("#report-editor").contentDocument?.querySelector(".CodeMirror")'))
    evaluate('window.savedFrame=document.querySelector("#report-editor");window.savedDoc=savedFrame.contentDocument;savedFrame.contentDocument.querySelector("[data-notes-view=edit]").click();savedFrame.contentDocument.querySelector(".CodeMirror textarea").focus()')
    c.call('Input.insertText', text='Workspace report draft. ')
    assert evaluate('savedFrame.contentWindow.notesEditorDirty()')
    panel('notes', False)
    evaluate('workspaceView.reset()')
    panel('notes', True)
    assert evaluate('savedFrame.contentDocument===savedDoc && savedFrame.contentWindow.notesEditorDirty()')
    panel('article', True)
    c.click('#material-tab-article')
    assert evaluate('document.querySelector("#material-tab-notes").getAttribute("aria-selected")==="true"')
    assert visible('#recording-status')
    evaluate('savedFrame.contentDocument.querySelector(".CodeMirror textarea").focus()')
    c.call('Input.dispatchKeyEvent', type='keyDown', key='z', code='KeyZ', windowsVirtualKeyCode=90, modifiers=2)
    wait_for(lambda: not evaluate('savedFrame.contentWindow.notesEditorDirty()'))

    # Preferences alone cannot generate, cancel or select work (trap all fetches).
    evaluate('window.originalFetch=fetch;window.visibilityCalls=[];window.fetch=(...args)=>{visibilityCalls.push(args[0]);return originalFetch(...args)}')
    for key in ['video', 'transcript', 'notes', 'article', 'technical', 'speakers', 'translation']:
        evaluate(f'workspaceView.setPanel({json.dumps(key)},false);workspaceView.setPanel({json.dumps(key)},true)')
    assert evaluate('visibilityCalls') == []
    # Active progress and errors remain visible when every optional region is hidden.
    # Assert atomically: actual fixture polling must not race a synthetic live snapshot.
    assert evaluate('''(()=>{
      document.dispatchEvent(new CustomEvent('recording-snapshot',{detail:{snapshot:{folder:'original',speech:[],running:true,has_ready_transcript:true,diarization_progress:{label:'Active participants',completed:1,total:2}},job:{status:'running',task:'diarize'}}}));
      for(const key of ['video','transcript','notes','article','technical','speakers','translation'])workspaceView.setPanel(key,false);
      return document.querySelector('#diarization-progress').checkVisibility() && document.querySelector('#recording-stop').checkVisibility();
    })()''')
    assert evaluate('''(()=>{
      document.dispatchEvent(new CustomEvent('recording-snapshot',{detail:{snapshot:{folder:'original',speech:[],has_ready_transcript:true},job:{status:'error',error:'Fixture failure'}}}));
      return document.querySelector('#recording-job-error').checkVisibility() && document.querySelector('#recording-retry').checkVisibility() && document.querySelector('#recording-job-error').textContent.includes('Fixture failure');
    })()''')
    assert len(list((root / 'output/jobs').glob('*/job.json'))) == 1
    # Reset via the menu itself, then invalid/outdated storage recovery and navigation.
    evaluate('document.querySelector("#workspace-view-menu").open=true')
    c.click('#workspace-view-menu button')
    assert visible('#shared-player') and not visible('#stage-notes')
    for bad in ['broken json', '{"version":99,"panels":{"video":false}}', '{"version":1,"layout":"floating","panels":{"video":"false"}}']:
        evaluate(f'localStorage.setItem("video-descriptor:ui:workspace",{json.dumps(bad)})')
        evaluate('window.beforeWorkspaceReload=true')
        c.call('Page.reload')
        wait_for(lambda: evaluate('!window.beforeWorkspaceReload && !!document.querySelector("#speech-feed .utterance")'))
        assert visible('#shared-player') and visible('#speech-feed') and not visible('#stage-notes')
        assert evaluate('document.documentElement.dataset.workspaceLayout') == 'side'
    evaluate('workspaceView.setLayout("stacked");window.workspaceURL=location.href')
    url = evaluate('workspaceURL')
    # The library shell has no recording panels, so it carries no View entry.
    evaluate('location.href="/#settings"')
    wait_for(lambda: evaluate('location.pathname==="/" && !!document.querySelector(".desktop-menu-bar #desktop-view-menu")'))
    assert evaluate('!!document.querySelector(".desktop-menu-bar #desktop-view-menu")')
    assert evaluate('JSON.parse(localStorage.getItem("video-descriptor:ui:workspace")).layout') == 'stacked'
    evaluate('location.hash="diagnostics"')
    evaluate(f'location.href={json.dumps(url)}')
    wait_for(lambda: evaluate('location.pathname==="/create" && !!document.querySelector("#speech-feed .utterance")'))
    assert evaluate('document.documentElement.dataset.workspaceLayout') == 'stacked'
    assert evaluate('!!document.querySelector(".desktop-menu-bar #workspace-view-menu [value=stacked]").checked')
    assert evaluate('document.documentElement.dataset.workspaceLayout') == 'stacked'
    assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
    print('PASS: workspace defaults, seven toggles, layouts, reload/reset/invalid storage, four widths, empty state, editor identity/dirty/Undo, no visibility API calls, progress/errors, navigation; real Edge fixture, no inference', flush=True)
