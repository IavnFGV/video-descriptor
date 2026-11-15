"""Current View controls and tab-only materials, using disposable recording fixtures."""
import json


def run(c, wait_for, out):
    evaluate = c.evaluate
    key = 'video-descriptor:ui:workspace'
    assert evaluate('document.documentElement.dataset.workspaceTab') == 'transcript'
    assert evaluate(f'localStorage.getItem({json.dumps(key)})===window.viewInitialBytes')
    assert evaluate('''[...document.querySelectorAll('#workspace-view-menu [data-panel]')].map(e=>e.dataset.panel).join(',')==='video,speakers' ''')
    assert evaluate('document.querySelectorAll("#workspace-view-menu [name=workspace-layout]").length===2')
    wait_for(lambda: evaluate('!document.querySelector("#construction-model").disabled'), timeout=30)
    c.click('#workspace-tab-notes')
    wait_for(lambda: evaluate('!!document.querySelector("#report-editor").contentDocument?.querySelector(".CodeMirror")'), timeout=35)
    evaluate('''window.viewFixture={player:document.querySelector('#process-video'),frame:document.querySelector('#report-editor'),
      doc:document.querySelector('#report-editor').contentDocument,feed:document.querySelector('#speech-feed'),url:location.href,
      history:history.length,speech:document.querySelector('#recording-speech').value,report:document.querySelector('#recording-notes').value};
      viewFixture.player.currentTime=45;viewFixture.doc.querySelector('[data-notes-view=edit]').click();
      viewFixture.doc.querySelector('.CodeMirror textarea').focus();window.viewMutations=[];window.viewFetch=fetch;
      window.fetch=(url,options)=>{if(options?.method&&options.method!=='GET')viewMutations.push(String(url));return viewFetch(url,options)}''')
    c.call('Input.insertText', text='View menu draft. ')
    assert evaluate('viewFixture.frame.contentWindow.notesEditorDirty()')

    def preserved():
        assert evaluate('''document.documentElement.dataset.workspaceTab==='notes' && document.querySelector('#stage-notes').checkVisibility() &&
          viewFixture.frame===document.querySelector('#report-editor') && viewFixture.doc===viewFixture.frame.contentDocument &&
          viewFixture.frame.contentWindow.notesEditorDirty() && viewFixture.player===document.querySelector('#process-video') &&
          viewFixture.player.currentTime===45 && viewFixture.feed===document.querySelector('#speech-feed') &&
          viewFixture.url===location.href && viewFixture.history===history.length &&
          viewFixture.speech===document.querySelector('#recording-speech').value && viewFixture.report===document.querySelector('#recording-notes').value''')

    c.click('#workspace-view-menu > summary')
    c.click('#workspace-view-menu [data-panel=video]')
    assert not evaluate('document.querySelector("#shared-player").checkVisibility()')
    preserved()
    c.click('#workspace-view-menu [data-panel=speakers]')
    assert evaluate('document.documentElement.dataset.viewSpeakers==="false"')
    preserved()
    c.click('#workspace-view-menu [name=workspace-layout][value=stacked]')
    assert evaluate('document.documentElement.dataset.workspaceLayout==="stacked"')
    preserved()
    c.click('#workspace-view-menu [data-panel=video]')
    assert evaluate('document.querySelector("#shared-player").checkVisibility()')
    preserved()
    c.click('.workspace-view-content > button')
    assert evaluate('document.documentElement.dataset.workspaceLayout==="side" && document.documentElement.dataset.viewVideo==="true" && document.documentElement.dataset.viewSpeakers==="true"')
    preserved()
    flags = json.loads(evaluate(f'localStorage.getItem({json.dumps(key)})'))['panels']
    assert {name: flags[name] for name in ['transcript', 'notes', 'article', 'translation', 'technical']} == {
        'transcript': False, 'notes': False, 'article': True, 'translation': True, 'technical': True}
    # Other-window preferences cannot hide the active material or reset its dirty editor.
    evaluate('''const key='video-descriptor:ui:workspace',value=JSON.parse(localStorage.getItem(key));
      value.layout='stacked';for(const key of Object.keys(value.panels))value.panels[key]=false;
      window.viewForeignBytes=' '+JSON.stringify(value)+' ';localStorage.setItem(key,viewForeignBytes);
      dispatchEvent(new StorageEvent('storage',{key,newValue:viewForeignBytes}));''')
    assert evaluate(f'localStorage.getItem({json.dumps(key)})===viewForeignBytes')
    assert not evaluate('document.querySelector("#shared-player").checkVisibility()')
    preserved()
    c.click('.workspace-view-content > button')
    preserved()
    assert evaluate(f'Object.entries(JSON.parse(localStorage.getItem({json.dumps(key)})).panels).every(([key,value])=>value===(key==="video"||key==="speakers"))')
    c.call('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    assert evaluate('!document.querySelector("#workspace-view-menu").open && document.activeElement===document.querySelector("#workspace-view-menu > summary")')
    evaluate('viewFixture.doc.querySelector(".CodeMirror textarea").focus()')
    c.call('Input.dispatchKeyEvent', type='keyDown', key='z', code='KeyZ', windowsVirtualKeyCode=90, modifiers=2)
    wait_for(lambda: not evaluate('viewFixture.frame.contentWindow.notesEditorDirty()'))
    evaluate('viewFixture.doc.querySelector("[data-notes-view=read]").click()')

    for width, height in [(1440, 900), (1200, 820), (1024, 768), (760, 560), (375, 820)]:
        c.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
        for kind, panel in [('transcript', 'stage-speech'), ('notes', 'stage-notes'), ('article', 'stage-notes'),
                            ('details', 'recording-details'), ('processing', 'recording-processing-tab')]:
            c.click('#workspace-tab-' + kind)
            assert evaluate(f'document.querySelector("#{panel}").checkVisibility()'), (width, kind)
            assert evaluate('document.querySelectorAll("#workspace-tabs [role=tab]").length===5')
            assert not evaluate('document.querySelector("#workspace-view-empty").checkVisibility() || document.querySelector("#workspace-material-hint").checkVisibility()')
        c.click('#workspace-view-menu > summary')
        assert evaluate('''(()=>{const r=document.querySelector('.workspace-view-content').getBoundingClientRect();
          return r.left>=0&&r.top>=0&&r.right<=document.documentElement.clientWidth+1&&r.bottom<=innerHeight+1})()'''), width
        assert evaluate('document.documentElement.scrollWidth<=innerWidth+1'), width
        c.screenshot(out / f'view-menu-current-{width}.png')
        c.call('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    assert evaluate('viewMutations') == [], evaluate('viewMutations')
    assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
    print('PASS: compact View menu, actual controls/reset/storage preserve dirty editor/tab/version/history/player; all tabs accessible under retired flags, Undo, keyboard and 375-1440 px; no processing', flush=True)
