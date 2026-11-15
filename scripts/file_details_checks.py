"""File details tab checks against temporary artifacts; no inference or deletion."""
import json


def run(c, wait_for, root, out):
    evaluate = c.evaluate
    evaluate('''window.fileSnapshotReady=false;document.addEventListener('recording-snapshot',event=>{
      if(event.detail.snapshot.folder==='original')window.fileSnapshotReady=true;
    })''')
    c.fill('#recording-speech', 'original')
    wait_for(lambda: evaluate('window.fileSnapshotReady && document.querySelector("#recording-speech").value==="original" && new URLSearchParams(location.search).get("folder")==="original"'))
    evaluate('workspaceView.reset()')
    c.click('#workspace-tab-transcript')
    assert evaluate('document.querySelector("#stage-label").textContent==="Распознавание завершено"')
    assert evaluate('document.querySelector("#run-message").textContent===""')
    assert evaluate('document.querySelector("#source-coverage-notice").checkVisibility()')
    assert not evaluate('document.querySelector("#source-details").checkVisibility()')
    evaluate('''window.fileFixture={player:document.querySelector('#process-video'),
      frame:document.querySelector('#report-editor'),source:document.querySelector('#source-details'),
      title:document.querySelector('#source-title'),url:location.href,history:history.length,
      storage:localStorage.getItem('video-descriptor:ui:workspace')};
      fileFixture.player.currentTime=45;
      window.fileMutations=[];window.fileFetch=window.fetch;
      window.fetch=(url,options)=>{if(options?.method && options.method!=='GET')fileMutations.push(String(url));return fileFetch(url,options)}''')
    c.click('#workspace-tab-details')
    wait_for(lambda: evaluate('document.querySelector("#source-details").checkVisibility()'))
    assert evaluate('document.querySelector("#recording-details").contains(document.querySelector("#source-details"))')
    assert evaluate('!document.querySelector("#stage-speech").checkVisibility() && !document.querySelector("#stage-notes").checkVisibility()')
    assert evaluate('document.querySelector("#source-info").textContent.includes("Только фрагмент")')
    assert evaluate('document.documentElement.dataset.viewTechnical==="false"')
    assert evaluate('document.querySelector(".recording-speech-heading .recording-version").contains(document.querySelector("#delete-version"))')
    assert evaluate('document.querySelector("#stage-speech").contains(document.querySelector(".recording-speech-heading"))')
    assert not evaluate('document.querySelector("#recording-speech").checkVisibility()')
    c.fill('#source-title', 'Несохранённое название / Незбережена назва')
    c.click('#workspace-tab-transcript')
    assert evaluate('document.querySelector("#source-coverage-notice").checkVisibility()')
    c.click('#workspace-tab-details')
    assert evaluate('fileFixture.title===document.querySelector("#source-title") && fileFixture.title.value==="Несохранённое название / Незбережена назва"')
    c.click('#source-title-form button')
    wait_for(lambda: evaluate('document.querySelector("#source-title-status").textContent.includes("Название сохранено")'))
    titles = json.loads((root / 'output/lecture-titles.json').read_text(encoding='utf-8'))
    assert titles[str(root / 'data/meeting.mp4')] == 'Несохранённое название / Незбережена назва'
    c.click('#workspace-tab-transcript')
    assert evaluate('document.querySelector("#delete-version").checkVisibility()')
    c.click('#delete-version')
    assert evaluate('document.querySelector("#delete-version-dialog").open')
    assert evaluate('document.querySelector("#delete-version-name").textContent.includes("original")')
    assert evaluate('document.querySelector("#delete-version-heading").textContent.includes("расшифровки")')
    assert evaluate('document.activeElement.id==="cancel-delete-version"')
    c.click('#cancel-delete-version')
    assert (root / 'output/original/speech.json').is_file()
    assert evaluate('!document.querySelector("#stage-speech").contains(document.querySelector("#recording-stop"))')
    # End reaches Processing; Left returns to Details without adding history/preferences.
    c.click('#workspace-tab-transcript')
    c.call('Input.dispatchKeyEvent', type='keyDown', key='End', code='End', windowsVirtualKeyCode=35)
    assert evaluate('document.activeElement.id==="workspace-tab-processing"')
    c.call('Input.dispatchKeyEvent', type='keyDown', key='ArrowLeft', code='ArrowLeft', windowsVirtualKeyCode=37)
    assert evaluate('document.activeElement.id==="workspace-tab-details"')
    assert evaluate('document.querySelector("#workspace-tab-panel").getAttribute("aria-labelledby")==="workspace-tab-details"')
    assert evaluate('document.querySelectorAll("#workspace-tabs [tabindex=\\"0\\"]").length===1')
    for width, height in [(1440, 900), (1200, 820), (760, 560), (375, 820)]:
        c.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
        assert evaluate('document.documentElement.scrollWidth<=innerWidth+1'), width
        assert evaluate('document.querySelector("#source-title").checkVisibility()'), width
        if width > 1000:
            assert evaluate('document.querySelector("#recording-details").getBoundingClientRect().left>=document.querySelector("#shared-player").getBoundingClientRect().right'), width
        c.screenshot(out / f'file-details-{width}.png')
        c.click('#workspace-tab-transcript')
        assert evaluate('document.querySelector("#recording-speech").getBoundingClientRect().width>=200'), width
        assert evaluate('''(()=>{const button=document.querySelector('#delete-version').getBoundingClientRect(),
          panel=document.querySelector('#stage-speech').getBoundingClientRect(),
          tabs=document.querySelector('#workspace-tabs').getBoundingClientRect();
          return button.width>0 && button.left>=panel.left && button.right<=panel.right+1 &&
            button.top>=tabs.bottom && button.bottom<=document.querySelector('#speech-feed').getBoundingClientRect().top;})()'''), width
        c.screenshot(out / f'transcript-version-actions-{width}.png')
        c.click('#workspace-tab-details')
    # The warning follows actual coverage, not just the existence of a transcript.
    evaluate('Object.defineProperty(fileFixture.player,"duration",{value:600,configurable:true});fileFixture.player.dispatchEvent(new Event("loadedmetadata"))')
    c.click('#workspace-tab-transcript')
    assert evaluate('document.querySelector("#source-coverage-notice").hidden')
    evaluate('delete fileFixture.player.duration;fileFixture.player.dispatchEvent(new Event("loadedmetadata"))')
    assert evaluate('document.querySelector("#source-coverage-notice").checkVisibility()')
    evaluate('workspaceView.setPanel("video",false);workspaceView.setPanel("transcript",false)')
    c.click('#workspace-tab-details')
    assert evaluate('document.querySelector("#source-details").checkVisibility() && !document.querySelector("#workspace-view-empty").checkVisibility()')
    evaluate('workspaceView.reset()')
    assert evaluate('''fileFixture.player===document.querySelector('#process-video') && fileFixture.player.currentTime===45 &&
      fileFixture.frame===document.querySelector('#report-editor') && fileFixture.source===document.querySelector('#source-details') &&
      fileFixture.history===history.length && fileFixture.url===location.href &&
      fileFixture.storage===localStorage.getItem('video-descriptor:ui:workspace')'''), evaluate('''({
        player:fileFixture.player===document.querySelector('#process-video'),time:fileFixture.player.currentTime,
        frame:fileFixture.frame===document.querySelector('#report-editor'),source:fileFixture.source===document.querySelector('#source-details'),
        history:history.length,beforeHistory:fileFixture.history,url:location.href,beforeUrl:fileFixture.url,
        storage:localStorage.getItem('video-descriptor:ui:workspace'),beforeStorage:fileFixture.storage})''')
    assert evaluate('window.fileMutations') == ['/output/original/title.json']
    for tab in ['notes', 'article', 'details', 'processing']:
        c.click('#workspace-tab-' + tab)
        assert not evaluate('document.querySelector("#recording-speech").checkVisibility()'), tab
        assert not evaluate('document.querySelector("#record-menu").checkVisibility()'), tab
    assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
    print('PASS: file details tab, partial coverage warning, title draft/save, delete confirmation/cancel, keyboard, DOM/history/storage and responsive layout; no inference or deletion', flush=True)
