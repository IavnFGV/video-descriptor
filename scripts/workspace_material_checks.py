"""Unified production tabs: real editor/guards; media time is a fixture shim."""
import json


def run(c, wait_for, root, out, empty_article=False):
    evaluate = c.evaluate

    def visible(selector):
        return evaluate(f'document.querySelector({json.dumps(selector)}).checkVisibility()')

    def ready(name):
        wait_for(lambda: evaluate(f'''document.querySelector('#report-editor').contentDocument?.location.pathname.includes({json.dumps(name + '/report.html')}) &&
          !!document.querySelector('#report-editor').contentDocument.querySelector('.CodeMirror')'''), timeout=35)

    def key(name, code, modifiers=0):
        c.call('Input.dispatchKeyEvent', type='keyDown', key=name, code=name, windowsVirtualKeyCode=code, modifiers=modifiers)

    evaluate('''workspaceView.reset();window.unifiedFixture={player:document.querySelector('#process-video'),
      frame:document.querySelector('#report-editor'),feed:document.querySelector('#speech-feed'),
      speech:document.querySelector('#recording-speech').value,history:history.length,
      storage:localStorage.getItem('video-descriptor:ui:workspace')};
      history.replaceState({sentinel:'tabs'},'',location.pathname+location.search+'#tabs');
      window.unifiedMutations=[];window.unifiedFetch=fetch;
      window.fetch=(url,options)=>{if(options?.method && options.method!=='GET')unifiedMutations.push(String(url));return unifiedFetch(url,options)}''')
    c.click('#workspace-tab-notes')
    assert visible('#material-notes-controls') and not visible('.material-tabs')
    assert not visible('#stage-speech') and visible('#stage-notes')
    assert evaluate('document.documentElement.dataset.workspaceTab==="notes"')
    c.fill('#recording-notes', '/output/notes-b/report.html')
    ready('notes-b')
    # A newly completed opposite-kind result must not change the visible kind.
    evaluate('''window.beforeInventoryDoc=unifiedFixture.frame.contentDocument;window.unifiedInventorySeen=false;window.unifiedInventoryRestored=false;
      window.beforeInventoryFetch=fetch;window.fetch=async(url,options)=>{
        const response=await beforeInventoryFetch(url,options);
        if(String(url).startsWith('/api/recording?')){
          if(unifiedInventorySeen){unifiedInventoryRestored=true;return response;}
          const value=await response.clone().json(),report=value.reports.find(item=>item.result_kind!=='article');
          value.reports.unshift({...report,result_kind:'article',url:report.url+'?new-material=1'});
          unifiedInventorySeen=true;return new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
        }return response;
      }''')
    wait_for(lambda: evaluate('unifiedInventorySeen'), timeout=20)
    assert evaluate('''document.documentElement.dataset.workspaceTab==='notes' &&
      document.querySelector('#material-tab-notes').getAttribute('aria-selected')==='true' &&
      unifiedFixture.frame.contentDocument===beforeInventoryDoc''')
    wait_for(lambda: evaluate('unifiedInventoryRestored'), timeout=20)
    evaluate('window.fetch=beforeInventoryFetch')
    evaluate('''window.notesDoc=unifiedFixture.frame.contentDocument;
      notesDoc.querySelector('[data-notes-view=edit]').click();notesDoc.querySelector('.CodeMirror textarea').focus()''')
    c.call('Input.insertText', text='Unified draft. ')
    assert evaluate('unifiedFixture.frame.contentWindow.notesEditorDirty()')
    # Hiding the same report preserves the document, draft and its undo history.
    c.click('#workspace-tab-transcript')
    c.click('#workspace-tab-notes')
    assert evaluate('unifiedFixture.frame.contentDocument===notesDoc && unifiedFixture.frame.contentWindow.notesEditorDirty()')
    blocked_url = evaluate('location.href')
    c.click('#workspace-tab-article')
    assert evaluate('document.activeElement.id==="workspace-tab-notes" && document.documentElement.dataset.workspaceTab==="notes"')
    assert evaluate('location.href') == blocked_url
    assert visible('#recording-status')
    evaluate('notesDoc.querySelector(".CodeMirror textarea").focus()')
    key('z', 90, 2)
    wait_for(lambda: not evaluate('unifiedFixture.frame.contentWindow.notesEditorDirty()'))
    key('Z', 90, 10)
    wait_for(lambda: evaluate('unifiedFixture.frame.contentWindow.notesEditorDirty()'))
    key('z', 90, 2)
    wait_for(lambda: not evaluate('unifiedFixture.frame.contentWindow.notesEditorDirty()'))
    evaluate('notesDoc.querySelector("[data-notes-view=read]").click()')
    # Real timestamp dispatch in the embedded preview reaches the same parent player.
    evaluate('''notesDoc.querySelector('button[data-time="60"]').click()''')
    assert evaluate('unifiedFixture.player.currentTime===60')
    c.click('#workspace-tab-article')
    if empty_article:
        assert evaluate('document.querySelector("#report-editor-card").hidden')
        assert 'Статья ещё не создана' in c.visible_text('#recording-notes-origin')
        assert visible('#construction-article')
    else:
        ready('article-a')
        assert visible('#material-article-controls')
    c.click('#workspace-tab-notes')
    ready('notes-b')
    assert evaluate('document.querySelector("#recording-notes").value==="/output/notes-b/report.html"')
    # Keyboard uses the shared vd-tabs semantics, including wraparound.
    for name, code, target in [('ArrowRight', 39, 'article'), ('End', 35, 'all'), ('Home', 36, 'transcript'), ('ArrowLeft', 37, 'all')]:
        key(name, code)
        assert evaluate('document.activeElement.id') == 'workspace-tab-' + target
    assert evaluate('localStorage.getItem("video-descriptor:ui:workspace")===unifiedFixture.storage')
    # Compatibility restores defaults (materials off), not the transient override.
    assert not visible('#stage-notes') and visible('#stage-speech')
    evaluate('workspaceView.setPanel("notes",true);workspaceView.setPanel("article",true)')
    assert visible('.material-tabs') and visible('#stage-speech')
    c.click('#workspace-tab-notes')
    ready('notes-b')
    for width, height in [(1440, 900), (1200, 820), (1024, 768), (760, 560), (375, 820)]:
        c.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
        geometry = evaluate('''(()=>{const rect=id=>{const r=document.getElementById(id).getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,w:r.width}};
          return {video:rect('shared-player'),tabs:rect('workspace-tabs'),notes:rect('stage-notes'),overflow:document.documentElement.scrollWidth>innerWidth+1}})()''')
        assert not geometry['overflow'], (width, geometry)
        video, tabs, notes = (geometry[k] for k in ['video', 'tabs', 'notes'])
        if width > 1000:
            assert abs(video['y'] - tabs['y']) < 2 and tabs['x'] >= video['right'], geometry
        else:
            assert tabs['y'] >= video['bottom'] and abs(tabs['x'] - video['x']) < 2, geometry
        assert abs(notes['y'] - tabs['bottom'] - 16) < 2, geometry
        evaluate('''document.querySelector('#report-editor').contentDocument.querySelector('button[data-time="60"]').click()''')
        assert evaluate('unifiedFixture.player.currentTime===60')
        c.screenshot(out / f'unified-tabs-{width}{"-empty" if empty_article else ""}.png')
    evaluate('workspaceView.setLayout("stacked")')
    c.call('Emulation.setDeviceMetricsOverride', width=1440, height=900, deviceScaleFactor=1, mobile=False)
    assert evaluate('document.querySelector("#workspace-tabs").getBoundingClientRect().top>=document.querySelector("#shared-player").getBoundingClientRect().bottom')
    evaluate('workspaceView.setLayout("side");workspaceView.setPanel("video",false);workspaceView.setPanel("transcript",false)')
    c.click('#workspace-tab-notes')
    assert not visible('#shared-player') and visible('#stage-notes')
    assert evaluate('document.querySelector(".stage-content").getBoundingClientRect().width>=document.querySelector(".studio-layout").getBoundingClientRect().width-2')
    evaluate('workspaceView.reset()')
    c.click('#workspace-tab-notes')
    key('Home', 36)
    assert evaluate('''Math.abs(document.querySelector('#stage-speech').getBoundingClientRect().top-
      document.querySelector('#workspace-tabs').getBoundingClientRect().bottom-16)<2''')
    assert evaluate('''(()=>{const strip=document.querySelector('#workspace-tabs'),style=getComputedStyle(document.activeElement);
      return strip.classList.contains('vd-tabs') && getComputedStyle(strip).gap==='8px' &&
      document.activeElement.matches(':focus-visible') && style.outlineWidth==='3px' && style.outlineStyle==='solid' &&
      [...strip.querySelectorAll('[role=tab]')].filter(tab=>tab.tabIndex===0).length===1})()''')
    c.call('Emulation.setEmulatedMedia', features=[{'name': 'forced-colors', 'value': 'active'}])
    c.screenshot(out / 'unified-tabs-forced-colors.png')
    c.call('Emulation.setEmulatedMedia', features=[])
    assert evaluate('''unifiedFixture.player===document.querySelector('#process-video') && unifiedFixture.feed===document.querySelector('#speech-feed') &&
      unifiedFixture.frame===document.querySelector('#report-editor') && unifiedFixture.speech===document.querySelector('#recording-speech').value &&
      history.length===unifiedFixture.history && history.state.sentinel==='tabs' && location.hash==='#tabs' '''), evaluate('''({speech:document.querySelector('#recording-speech').value,original:unifiedFixture.speech,
        history:history.length,originalHistory:unifiedFixture.history,state:history.state,hash:location.hash,
        player:unifiedFixture.player===document.querySelector('#process-video'),feed:unifiedFixture.feed===document.querySelector('#speech-feed')})''')
    assert evaluate('unifiedMutations') == []
    assert len(list((root / 'output/jobs').glob('*/job.json'))) == 1
    assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
    # A sole enabled material opens its own tab on a fresh document, not an
    # incompatible hidden kind. Preference loading must not rewrite the bytes.
    for kind in ['notes', 'article']:
        saved = json.dumps({'version': 1, 'layout': 'side', 'panels': {
            'video': True, 'transcript': False, 'notes': kind == 'notes', 'article': kind == 'article'}})
        evaluate(f'''localStorage.setItem('video-descriptor:ui:workspace',{json.dumps(saved)});window.beforeMaterialReload=true''')
        c.call('Page.navigate', url=evaluate('location.origin') + '/create?folder=original')
        wait_for(lambda: evaluate('''!window.beforeMaterialReload && document.body?.classList.contains('has-recording') &&
          document.querySelector('#recording-notes')?.options.length>1'''), timeout=35)
        assert evaluate('document.documentElement.dataset.workspaceTab') == kind
        assert evaluate(f'document.querySelector("#material-tab-{kind}").getAttribute("aria-selected")==="true"')
        assert visible('#material-' + kind + '-controls') and visible('#stage-notes')
        assert not visible('#stage-speech')
        assert evaluate('localStorage.getItem("video-descriptor:ui:workspace")') == saved
        assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
    print('PASS: unified notes/article tabs, empty material, versions, dirty guard, hide/Undo/Redo, timestamps, keyboard, geometry, layout/video flags, forced colors; no generated work', flush=True)
