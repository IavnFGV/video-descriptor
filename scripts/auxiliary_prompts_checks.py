"""Retired auxiliary editor: no UI/API initialization; retain legacy data and builder prompts."""
import hashlib
import json

from acceptance_ui import read_http


def run(c, wait_for, root, out, web=False):
    evaluate = c.evaluate
    legacy_file = root / '.devcontainer/model-prompts.json'
    original = hashlib.sha256(legacy_file.read_bytes()).hexdigest()

    def retired():
        assert not evaluate('document.querySelector("#workspace-view-menu [data-panel=technical]")')
        assert evaluate('window.auxRequests') == [], evaluate('window.auxRequests')
        assert evaluate('''!document.querySelector('#prompt-settings-panel').checkVisibility() &&
          !document.querySelector('#model-prompt').checkVisibility() && !document.querySelector('#open-prompt-settings').checkVisibility() &&
          !document.querySelector('a[href="#prompt-settings-panel"]') &&
          document.querySelector('#prompt-task').onchange===null && document.querySelector('#reset-prompt').onclick===null &&
          document.querySelector('#prompt-settings-form').onsubmit===null''')
        assert evaluate('studioDraft.prompts()') == {'filter': 'Fixture legacy draft', 'quiz_explanation': 'Fixture explanation draft'}
        assert evaluate('studioDraft.promptTask()') == 'quiz_explanation'
        assert hashlib.sha256(legacy_file.read_bytes()).hexdigest() == original

    assert evaluate('recordingUI.native') == (not web)
    evaluate('''window.auxFixture={player:document.querySelector('#process-video'),frame:document.querySelector('#report-editor')};
      document.querySelector('#model-prompt').value='Unreachable retired input';
      document.querySelector('#model-prompt').dispatchEvent(new Event('input',{bubbles:true}));
      document.querySelector('#prompt-settings-panel').open=true;
      document.querySelector('#open-prompt-settings').click()''')
    for technical in [True, False]:
        evaluate(f'workspaceView.setPanel("technical",{json.dumps(technical)})')
        for tab in ['transcript', 'notes', 'article', 'details', 'processing']:
            c.click('#workspace-tab-' + tab)
            retired()
    assert evaluate('''auxFixture.player===document.querySelector('#process-video') &&
      auxFixture.frame===document.querySelector('#report-editor')''')

    for kind in ['notes', 'article']:
        c.click('#workspace-tab-' + kind)
        wait_for(lambda: evaluate('!document.querySelector("#construction-article").disabled'), timeout=30)
        c.fill('#recording-' + kind, '__new__')
        c.fill('#construction-provider', 'ollama')
        wait_for(lambda: evaluate('[...document.querySelector("#construction-model").options].some(option=>option.value==="model-a")'), timeout=30)
        c.fill('#construction-model', 'model-a')
        wait_for(lambda: evaluate('!document.querySelector("#construction-save").disabled'), timeout=30)
        field = '#construction-article-prompt' if kind == 'article' else '#construction-prompt'
        if kind == 'notes':
            c.click('#construction-notes-instruction > summary')
        assert evaluate(f'document.querySelector({json.dumps(field)}).checkVisibility()')
        c.fill(field, 'Fixture ' + kind + ' instruction')
        c.click('#workspace-tab-details')
        c.click('#workspace-tab-' + kind)
        assert evaluate(f'document.querySelector({json.dumps(field)}).value') == 'Fixture ' + kind + ' instruction'
        c.click('#construction-save')
        wait_for(lambda: evaluate('document.querySelector("#construction-status").textContent.includes("Настройки сохранены")'))
        saved = json.loads((root / '.devcontainer/construction-settings.json').read_text(encoding='utf-8'))
        assert saved['article_prompt' if kind == 'article' else 'prompt'] == 'Fixture ' + kind + ' instruction'
        if kind == 'article':
            assert saved['prompt'] == 'Fixture notes instruction'
        retired()
        for width in [1200, 760, 375]:
            c.call('Emulation.setDeviceMetricsOverride', width=width, height=900, deviceScaleFactor=1, mobile=False)
            assert evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            c.screenshot(out / f'aux-prompts-retired-{kind}-{width}-{"web" if web else "native"}.png')
        c.click('#cancel-new-notes')
    assert evaluate('auxMutations.every(path=>path==="/api/construction-plan"||path==="/api/construction-settings")'), evaluate('auxMutations')
    # Exercise the preserved backend independently; the recording page must never call it.
    api = json.loads(read_http(evaluate('location.origin') + '/api/prompts'))
    assert api['prompts']['filter'] == 'Fixture saved legacy filter'
    assert api['prompts']['quiz_explanation'] == 'Fixture saved legacy explanation'
    c.call('Page.navigate', url=evaluate('location.href').split('#')[0] + '#prompt-settings-panel')
    wait_for(lambda: evaluate('document.querySelector("#recording-notes")?.options.length>1 && !!document.querySelector("#report-editor").contentDocument?.querySelector(".CodeMirror")'))
    retired()
    assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
    print('PASS: auxiliary editor/link inert with technical on/off and legacy hash; no prompt API calls; legacy settings/drafts retained; notes/article prompts edit/save independently, responsive native/web UI; no generation', flush=True)
