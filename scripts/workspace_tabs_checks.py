"""Focused production workspace tab checks using the isolated recording fixture."""

import time


def run(c, wait_for, out):
    evaluate = c.evaluate
    c.call('Emulation.setFocusEmulationEnabled', enabled=True)
    evaluate("workspaceView.setPanel('notes',true);workspaceView.setPanel('translation',true)")
    wait_for(lambda: evaluate('document.querySelector("#stage-notes").checkVisibility()'))
    evaluate('''window.tabFixture={player:document.querySelector('#process-video'),
      feed:document.querySelector('#speech-feed'),frame:document.querySelector('#report-editor'),
      url:location.href,history:history.length,storage:localStorage.getItem('video-descriptor:ui:workspace')};
      tabFixture.player.currentTime=45''')
    c.click('#workspace-tab-transcript')
    assert evaluate('document.querySelector("#speech-feed").checkVisibility()')
    assert not evaluate('document.querySelector("#stage-notes").checkVisibility()')
    assert not evaluate('document.querySelector("#recording-translation-panel").checkVisibility()')
    assert evaluate('''tabFixture.url===location.href && tabFixture.history===history.length &&
      tabFixture.storage===localStorage.getItem('video-descriptor:ui:workspace')''')
    evaluate('workspaceView.refresh();workspaceView.refresh()')
    time.sleep(11)  # Allow the recording inventory polling interval to run.
    assert evaluate('''document.activeElement.id==='workspace-tab-transcript' &&
      document.querySelector('#workspace-tab-transcript').getAttribute('aria-selected')==='true' &&
      tabFixture.player===document.querySelector('#process-video') && tabFixture.player.currentTime===45 &&
      tabFixture.feed===document.querySelector('#speech-feed') && tabFixture.frame===document.querySelector('#report-editor')''')
    c.call('Input.dispatchKeyEvent', type='keyDown', key='ArrowLeft', code='ArrowLeft', windowsVirtualKeyCode=37)
    assert evaluate('document.activeElement.id==="workspace-tab-all"')
    assert evaluate('document.querySelector("#stage-notes").checkVisibility() && !document.querySelector("#recording-translation-panel").checkVisibility()')
    assert evaluate('!document.querySelector("#workspace-view-menu [data-panel=translation]")')
    assert evaluate('!document.querySelector("#prompt-task option[value=translate]")')
    assert evaluate('''['#subtitle-mode-label','#download-ru-srt','#download-translation'].every(
      selector=>!document.querySelector(selector).checkVisibility())''')
    evaluate("document.querySelector('#subtitle-mode').value='ru';document.querySelector('#subtitle-mode').dispatchEvent(new Event('change'))")
    assert evaluate('document.querySelector("#speech-feed .subtitle-original").checkVisibility()')
    assert not evaluate('document.querySelector("#speech-feed .subtitle-ru").checkVisibility()')
    c.call('Input.dispatchKeyEvent', type='keyDown', key='Home', code='Home', windowsVirtualKeyCode=36)
    assert evaluate('document.activeElement.id==="workspace-tab-transcript"')
    c.call('Input.dispatchKeyEvent', type='keyDown', key='End', code='End', windowsVirtualKeyCode=35)
    assert evaluate('document.activeElement.id==="workspace-tab-all"')
    assert evaluate("document.querySelectorAll('#workspace-tabs [tabindex=\"0\"]').length===1")
    evaluate("workspaceView.setPanel('transcript',false)")
    assert not evaluate('document.querySelector("#speech-feed").checkVisibility()')
    c.click('#workspace-tab-transcript')
    assert evaluate('document.querySelector("#speech-feed").checkVisibility()')
    assert evaluate('document.documentElement.getAttribute("data-view-transcript")==="false"')
    c.click('#workspace-tab-all')
    assert not evaluate('document.querySelector("#speech-feed").checkVisibility()')
    evaluate("workspaceView.setPanel('transcript',true)")
    for width in [1440, 1024, 760, 375]:
        c.call('Emulation.setDeviceMetricsOverride', width=width, height=820, deviceScaleFactor=1, mobile=False)
        assert evaluate('document.documentElement.scrollWidth<=innerWidth+1'), width
        c.screenshot(out / f'workspace-tabs-{width}.png')
    assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
    print('PASS: workspace tabs, compatibility view, keyboard, focus, refresh, DOM, storage and responsive fixture', flush=True)
