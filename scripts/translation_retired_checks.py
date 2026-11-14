"""Translation retirement acceptance on disposable recording fixtures."""

import json


def run(c, wait_for, root, out):
    evaluate = c.evaluate
    evaluate("workspaceView.setPanel('translation',true);workspaceView.setPanel('notes',true)")
    assert evaluate('!document.querySelector("#workspace-view-menu [data-panel=translation]")')
    for selector in ['#recording-translation-panel', '#recording-translate', '#subtitle-mode-label',
                     '#download-ru-srt', '#download-translation', '#speech-feed .subtitle-ru']:
        assert not evaluate(f'document.querySelector({json.dumps(selector)}).checkVisibility()'), selector
    assert evaluate('document.querySelector("#speech-feed .subtitle-original").checkVisibility()')
    assert evaluate('!document.querySelector("#prompt-task option[value=translate]")')
    evaluate("constructionUI.openSettings('notes')")
    wait_for(lambda: evaluate('!document.querySelector("#construction-run").disabled'))
    assert evaluate('!document.querySelector("#construction-translate-after").checkVisibility()')
    # Even a restored historical checkbox value must not start translation.
    evaluate('''document.querySelector('#construction-translate-after').checked=true;
      window.retiredRequest=null;window.retiredPostprocess=recordingUI.postprocess;
      recordingUI.postprocess=async(task,options)=>{retiredRequest={task,...options};throw Error('fixture capture')};
      document.querySelector('#construction-run').click()''')
    wait_for(lambda: evaluate('!!window.retiredRequest'))
    assert evaluate('retiredRequest.task==="notes" && retiredRequest.translate_after===false')
    evaluate('recordingUI.postprocess=retiredPostprocess')
    # Editing an original reply must keep the stored translation, though its fields are absent visually.
    evaluate("document.querySelector('#speech-feed .edit-subtitle').click()")
    wait_for(lambda: evaluate('!!document.querySelector("dialog.reply-editor[open]")'))
    assert evaluate('''(()=>{const form=document.querySelector('dialog.reply-editor form');
      return form.elements.translation.value==='Сохранённый перевод' &&
        !form.elements.translation.checkVisibility() && !form.elements.rightTranslation.checkVisibility();})()''')
    c.fill('dialog.reply-editor textarea[name=left]', 'Original edited without translation loss')
    c.click('dialog.reply-editor button[type=submit]')
    wait_for(lambda: evaluate('''!document.querySelector('dialog.reply-editor[open]') ||
      (()=>{const error=document.querySelector('dialog.reply-editor .error');return error?.textContent && error.textContent!=='Сохраняем…'})()'''))
    assert evaluate('!document.querySelector("dialog.reply-editor[open]")'), evaluate('''({error:document.querySelector('dialog.reply-editor .error')?.textContent,
      fields:[...document.querySelector('dialog.reply-editor form').elements].map(e=>({name:e.name,value:e.value}))})''')
    overlays = list((root / 'output').glob('*/transcript-edits.json'))
    assert overlays
    assert any('Сохранённый перевод' in p.read_text(encoding='utf-8') for p in overlays)
    for width in [1440, 1024, 760, 375]:
        c.call('Emulation.setDeviceMetricsOverride', width=width, height=820, deviceScaleFactor=1, mobile=False)
        assert evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        c.screenshot(out / f'translation-retired-{width}.png')
    assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
    base = evaluate('location.origin')
    c.call('Page.navigate', url=base + '/#settings')
    wait_for(lambda: evaluate('!!document.querySelector("#notes-dialog") && !!document.querySelector("#desktop-settings-index")'))
    assert evaluate('''['#translate-run','#ru-srt','#notes-translate-after'].every(
      selector=>!document.querySelector(selector).checkVisibility())''')
    assert evaluate('!document.querySelector("#local-default-help").textContent.includes("перевод")')
    assert evaluate('!document.querySelector("#ai-summary").textContent.includes("перевод")')
    c.screenshot(out / 'translation-retired-native-settings.png')
    print('PASS: retired translation controls, persisted flag, prompt list, notes payload, reply edit/data preservation, four widths', flush=True)
