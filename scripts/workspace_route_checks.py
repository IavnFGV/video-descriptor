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
      try{await recordingSelection.select({folder:'another-recording'});return !asked&&!closed}
      finally{frame.notesEditorDirty=dirty;window.mayLeaveQuickReply=mayLeave;window.closeQuickReplyEdit=close}
    })()''')
    assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
    print('PASS: material paint does not write URL; explicit material/stage writers preserve hash and history state', flush=True)
