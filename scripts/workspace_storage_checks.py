"""Storage failure checks on a disposable production recording fixture."""


def run(c, wait_for, blocked_write):
    evaluate = c.evaluate
    wait_for(lambda: evaluate('!!document.querySelector("#speech-feed .utterance")'))
    assert evaluate('document.querySelector("#workspace-tabs").checkVisibility()')
    assert evaluate('document.querySelector("#speech-feed").checkVisibility()')
    evaluate('''document.querySelector('#playback-link').click();
      document.querySelector('#speech-engine').dispatchEvent(new Event('change'));
      workspaceView.setPanel('video',false)''')
    assert not evaluate('document.querySelector("#shared-player").checkVisibility()')
    assert not evaluate('document.querySelector("#playback-link").checked')
    evaluate('workspaceView.reset()')
    assert evaluate('document.querySelector("#shared-player").checkVisibility()'), evaluate('({body:document.body.className,hidden:document.querySelector("#shared-player").hidden,video:document.documentElement.dataset.viewVideo,tab:document.documentElement.dataset.workspaceTab})')
    assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
    # Page.reload returns before navigation commits. The old document already has
    # utterances, so require the new shell and its snapshot, not stale readiness.
    evaluate('window.beforeStorageReload=true')
    c.call('Page.reload')
    wait_for(lambda: evaluate('''!window.beforeStorageReload && document.body?.classList.contains('has-recording') &&
      !!document.querySelector('#speech-feed .utterance') && document.querySelector('#shared-player')?.hidden===false'''), timeout=35)
    assert evaluate('document.querySelector("#shared-player").checkVisibility()'), evaluate('({body:document.body.className,hidden:document.querySelector("#shared-player").hidden,video:document.documentElement.dataset.viewVideo,tab:document.documentElement.dataset.workspaceTab})')
    assert evaluate('document.querySelector("#playback-link").checked')
    assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
    print('PASS: blocked storage ' + ('writes' if blocked_write else 'reads') + ', controls and reload', flush=True)
