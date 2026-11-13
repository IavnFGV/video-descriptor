"""URL writer checks on a disposable recording fixture."""


def run(c, wait_for):
    evaluate = c.evaluate
    wait_for(lambda: evaluate('!!document.querySelector("#speech-feed .utterance")'))
    assert evaluate('!new URLSearchParams(location.search).has("material")')
    evaluate('''history.replaceState({sentinel:'preserve'},'',location.pathname+location.search+'#example');
      workspaceView.setPanel('notes',true);workspaceView.setPanel('article',true)''')
    c.click('#material-tab-article')
    assert evaluate('new URLSearchParams(location.search).get("material")==="article"')
    assert evaluate('location.hash==="#example" && history.state.sentinel==="preserve"')
    wait_for(lambda: evaluate('''document.querySelector('#report-editor').contentDocument?.location.pathname.includes('article-a/report.html') &&
      !!document.querySelector('#report-editor').contentDocument.querySelector('.CodeMirror')'''), timeout=35)
    evaluate('studioUI.openStage("speech")')
    assert evaluate('location.hash==="#example" && history.state.sentinel==="preserve"')
    assert evaluate('new URLSearchParams(location.search).get("stage")==="speech"')
    assert evaluate('''(async()=>{
      const frame=document.querySelector('#report-editor').contentWindow;
      const dirty=frame.notesEditorDirty, mayLeave=window.mayLeaveQuickReply, close=window.closeQuickReplyEdit;
      let asked=false,closed=false;
      frame.notesEditorDirty=()=>true;
      window.mayLeaveQuickReply=async()=>{asked=true;return true};
      window.closeQuickReplyEdit=()=>{closed=true};
      try{await recordingSelection.select({folder:'original'});return !asked&&!closed}
      finally{frame.notesEditorDirty=dirty;window.mayLeaveQuickReply=mayLeave;window.closeQuickReplyEdit=close}
    })()''')
    evaluate('''window.routeBefore=location.href;window.routeFrame=document.querySelector('#report-editor').contentWindow;
      window.routeDirty=routeFrame.notesEditorDirty;routeFrame.notesEditorDirty=()=>true;
      history.pushState({other:true},'',location.pathname+'?folder=original&stage=notes#other');
      history.back()''')
    wait_for(lambda: evaluate('location.href===window.routeBefore'))
    # A second traversal targets the synthetic other recording while the frame is dirty.
    evaluate('document.querySelector("#run-message").textContent="";history.forward()')
    wait_for(lambda: evaluate('document.querySelector("#run-message").textContent.includes("правки")'))
    assert evaluate('location.href===window.routeBefore')
    assert evaluate('document.querySelector("#report-editor").contentWindow===window.routeFrame')
    evaluate('routeFrame.notesEditorDirty=routeDirty')
    evaluate('''window.cleanRoute=location.href;
      history.pushState(null,'',location.pathname+'?folder=original&stage=speech#clean');history.back()''')
    wait_for(lambda: evaluate('location.href===window.cleanRoute'))
    evaluate('history.forward()')
    wait_for(lambda: evaluate('''new URLSearchParams(location.search).get('folder')==='original' &&
      document.querySelector('#recording-speech').value==='original' &&
      document.documentElement.dataset.workspaceTab==='transcript' '''), timeout=35)
    assert evaluate('location.hash==="#clean"')
    assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
    print('PASS: material paint does not write URL; explicit material/stage writers preserve hash and history state', flush=True)
