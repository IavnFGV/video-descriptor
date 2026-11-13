"""Real-asset Edge visual review. All API state is disposable/offline, never inference."""
import json


def native_fixture(path):
    caps = {name: {'available': True, 'ready': name == 'CPU', 'reason': 'Готово' if name == 'CPU' else 'Не подготовлено'} for name in ['CPU', 'GPU', 'NPU']}
    fixtures = {
        '/health': {'status': 'ok', 'app': 'video-descriptor-windows', 'instance': 'fixture', 'version': '0.9.3', 'build': 8},
        '/api/doctor': {'ffmpeg': True, 'ollama': {'ready': False}, 'diarization': {'state': 'configured', 'device': 'cpu'}, 'compute': {'selected': 'CPU', 'settings': {'speech_device': 'AUTO'}, 'capabilities': caps}},
        '/api/setup': {'completed': True, 'model_present': True, 'model_path': 'D:\\AI\\whisper-small', 'verified': True, 'download': {}, 'operation': {}},
        '/api/setup/ollama': {'url': 'http://127.0.0.1:11434', 'models': [], 'selected': '', 'message': 'Внешний сервер не подключён', 'service_ready': False},
        '/api/setup/diagnostics': {'hardware': {'cpu': 'Intel Core · демонстрационный стенд', 'intel_gpu': ['Intel Arc'], 'intel_npu': ['Intel AI Boost']}, 'inventory': {'devices': ['CPU']}, 'translation': {}, 'notes': {}, 'ocr': {}, 'diarization': {}, 'gemini': {}},
        '/api/components': {'components': [{'id': 'whisper', 'name': 'Распознавание', 'state': 'ready', 'device': 'CPU', 'message': 'Готово к работе'}, {'id': 'diarization', 'name': 'Участники', 'state': 'ready', 'device': 'cpu', 'requires_download': False, 'message': 'Локальная проверка сохранена'}, {'id': 'ollama', 'name': 'Ollama', 'state': 'not_installed', 'message': 'Подключите внешний сервер'}], 'profiles': {}, 'root': 'D:\\AI', 'preparation': {'state': 'ready', 'features': ['whisper', 'diarization']}},
        '/api/storage': {'components': 'D:\\AI', 'records': 'D:\\Записи', 'transfer': {}},
        '/api/native/events': [],
        '/api/updates': {'installed': {'version': '0.9.3', 'build': 8}, 'status': 'ok', 'update_available': False},
    }
    return fixtures.get(path)


def run(c, wait_for, root, base, before=False):
    out = root / 'windows-app/runtime/zero-config/desktop-design' / ('before' if before else 'after')
    out.mkdir(parents=True, exist_ok=True)
    metrics = []

    def check_menu_keyboard(menus):
        assert c.evaluate('document.querySelector("#workspace-view-menu").hidden') == ('workspace-view-menu' not in menus)
        for direction, code, step in [('ArrowRight', 39, 1), ('ArrowLeft', 37, -1)]:
            for i, menu in enumerate(menus):
                c.evaluate(f'document.getElementById({json.dumps(menu)}).open=true;document.querySelector({json.dumps("#" + menu + " > summary")}).focus()')
                c.call('Input.dispatchKeyEvent', type='keyDown', key=direction, code=direction, windowsVirtualKeyCode=code)
                target = menus[(i + step) % len(menus)]
                assert c.evaluate(f'document.activeElement===document.querySelector({json.dumps("#" + target + " > summary")})'), (direction, menu, target)
                assert c.evaluate('![...document.querySelectorAll(".desktop-menu-bar > details")].some(item=>item.open)')
        c.evaluate(f'document.getElementById({json.dumps(menus[0])}).open=true;document.querySelector({json.dumps("#" + menus[0] + " > summary")}).focus()')
        c.call('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
        assert c.evaluate(f'!document.getElementById({json.dumps(menus[0])}).open && document.activeElement===document.querySelector({json.dumps("#" + menus[0] + " > summary")})')

    def capture(name, width, height):
        c.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
        c.evaluate('window.scrollTo(0,0)')
        c.screenshot(out / f'{name}-{width}x{height}.png')
        value = c.evaluate('''({width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,errors:window.uiErrors,
          overflow:[...document.querySelectorAll('body *')].filter(e=>e.checkVisibility()&&getComputedStyle(e).position!=='fixed').map(e=>({id:e.id||e.className,right:e.getBoundingClientRect().right})).filter(r=>r.right>innerWidth+2).slice(0,8)})''')
        metrics.append({'screen': name, **value})
        assert value['scrollWidth'] <= width + 1, (name, value)
        assert not value['errors'], (name, value['errors'])

    workspace = c.evaluate('location.href')
    if not before:
        c.call('Emulation.setDeviceMetricsOverride', width=1200, height=800, deviceScaleFactor=1, mobile=False)
        check_menu_keyboard(['desktop-file-menu', 'workspace-view-menu', 'desktop-tools-menu', 'desktop-help-menu'])
        for menu in ['desktop-file-menu', 'workspace-view-menu', 'desktop-tools-menu', 'desktop-help-menu']:
            before_rect = c.evaluate('''(()=>{const r=document.querySelector('.desktop-header').getBoundingClientRect();
                return [r.x,r.y,r.width,r.height]})()''')
            c.click(f'#{menu} > summary')
            wait_for(lambda menu=menu: c.evaluate(f'document.getElementById({json.dumps(menu)}).open'))
            after_rect = c.evaluate('''(()=>{const r=document.querySelector('.desktop-header').getBoundingClientRect();
                return [r.x,r.y,r.width,r.height]})()''')
            assert after_rect == before_rect, (menu, before_rect, after_rect)
            c.click(f'#{menu} > summary')
    for width, height in [(1200, 800), (1440, 900)]:
        capture('recording', width, height)
        if not before:
            geometry=c.evaluate('''(()=>{const r=id=>{const v=document.getElementById(id).getBoundingClientRect();return {x:v.x,y:v.y,width:v.width,bottom:v.bottom}};return {video:r('shared-player'),speech:r('stage-speech'),feed:r('speech-feed')}})()''')
            assert geometry['speech']['width']>=420 and geometry['video']['width']>=300, geometry
            assert geometry['speech']['y']<260, geometry
            assert geometry['feed']['bottom']<=height-8, geometry
            assert c.evaluate('document.querySelectorAll(".desktop-menu-bar").length===1')
            assert c.evaluate('!document.querySelector(".vd-global-nav details")')
            assert c.evaluate('!document.querySelector(".vd-global-nav").checkVisibility() && !document.querySelector("#sidebar-toggle").checkVisibility()')
    if not before:
        c.evaluate('window.clipboardText="";Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async text=>{window.clipboardText=text}}})')
        c.click('#desktop-copy-transcript')
        wait_for(lambda:c.evaluate('clipboardText.includes("Реплика 0.")'))
        assert not c.evaluate('clipboardText.includes("Экспорт:")')
    c.evaluate('workspaceView.setLayout("stacked")')
    capture('stacked', 1200, 800)
    c.evaluate('workspaceView.setLayout("side");workspaceView.setPanel("notes",true);workspaceView.setPanel("article",true)')
    capture('materials', 1200, 800)
    c.evaluate('document.querySelector("#stage-notes").scrollIntoView({block:"start"})')
    c.screenshot(out / 'notes-editor-1200x800.png')
    if not before:
        assert c.evaluate('document.querySelector("#report-editor").getBoundingClientRect().top>=44')
        # No video overlay obscures material controls after scrolling down.
        assert c.evaluate('document.querySelector("#shared-player").getBoundingClientRect().bottom<=document.querySelector("#stage-notes").getBoundingClientRect().top')
    c.click('#material-tab-article')
    wait_for(lambda: c.evaluate('document.querySelector("#report-editor").contentWindow?.location.pathname.includes("article-a") && document.querySelector("#report-editor").contentDocument?.querySelector("#personal-preview")?.textContent.includes("Начало")'))
    capture('article', 1440, 900)
    c.evaluate('document.querySelector("#stage-notes").scrollIntoView({block:"start"})')
    c.screenshot(out / 'article-editor-1440x900.png')
    c.click('#material-tab-notes')
    if not before:
        # A real unsaved report blocks the new menu links, with no iframe replacement.
        wait_for(lambda: c.evaluate('''(()=>{const f=document.querySelector('#report-editor'),d=f.contentDocument;return f.contentWindow?.location.pathname.includes('/notes-') && d?.querySelector('.CodeMirror') && d.querySelector('[data-notes-view=edit]') && d.querySelector('#personal-preview')?.textContent.includes('Начало')})()'''))
        c.evaluate('window.reviewFrame=document.querySelector("#report-editor");window.reviewDoc=reviewFrame.contentDocument;reviewDoc.querySelector("[data-notes-view=edit]").click();reviewDoc.querySelector(".CodeMirror textarea").focus()')
        c.call('Input.insertText',text='Unsaved desktop design review. ')
        assert c.evaluate('reviewFrame.contentWindow.notesEditorDirty()')
        c.evaluate('document.querySelector("#desktop-file-menu").open=true')
        c.click('#desktop-file-menu a')
        assert c.evaluate('location.pathname==="/create" && reviewFrame.contentDocument===reviewDoc && reviewFrame.contentWindow.notesEditorDirty()')
        assert 'Сохраните' in c.visible_text('#recording-status')
        c.evaluate('document.querySelector("#desktop-tools-menu").open=true')
        c.click('#desktop-tools-menu a')
        assert c.evaluate('location.pathname==="/create" && reviewFrame.contentDocument===reviewDoc && reviewFrame.contentWindow.notesEditorDirty()')
        c.evaluate('reviewDoc.querySelector(".CodeMirror textarea").focus()')
        c.call('Input.dispatchKeyEvent',type='keyDown',key='z',code='KeyZ',windowsVirtualKeyCode=90,modifiers=2)
        wait_for(lambda:not c.evaluate('reviewFrame.contentWindow.notesEditorDirty()'))
    c.evaluate('workspaceView.reset();document.querySelector("#workspace-view-menu").open=true')
    capture('view-menu', 1200, 800)
    c.evaluate('document.querySelector("#workspace-view-menu").open=false')
    if not before:
        c.evaluate('document.querySelector("#desktop-help-menu").open=true')
        c.click('#desktop-help-menu button')
        assert c.evaluate('document.querySelector("#desktop-help-dialog").open')
        capture('help-dialog',1200,800)
        c.call('Input.dispatchKeyEvent',type='keyDown',key='Escape',code='Escape',windowsVirtualKeyCode=27)
        wait_for(lambda:c.evaluate('!document.querySelector("#desktop-help-dialog").open'))
        wait_for(lambda:c.evaluate('document.activeElement===document.querySelector("#desktop-help-menu summary")'),timeout=10)
    c.click('#speech-feed .edit-subtitle')
    wait_for(lambda: c.evaluate('!!document.querySelector("dialog.reply-editor[open]")'))
    capture('reply-dialog', 1200, 800)
    c.click('dialog.reply-editor .cancel')
    for route, screen in [('/#records', 'records'), ('/#new', 'new-record'), ('/#settings', 'settings'), ('/#diagnostics', 'diagnostics'), ('/output/', 'web-library')]:
        c.call('Page.navigate', url=base + route)
        wait_for(lambda route=route: c.evaluate('document.readyState==="complete" && location.href===' + json.dumps(base + route)))
        if screen == 'settings':
            wait_for(lambda: c.evaluate('document.querySelector("#component-summary")?.textContent.includes("Распознавание")'))
        for width, height in [(1200, 800), (1440, 900)]:
            capture(screen, width, height)
        if not before:
            assert c.evaluate('document.querySelectorAll(".desktop-menu-bar > details").length===4')
            assert c.evaluate('!!document.querySelector(".desktop-menu-bar #workspace-view-menu [data-panel=video]")')
            assert c.evaluate('document.querySelectorAll("#desktop-tools-menu a").length===2')
            assert c.evaluate('![...document.querySelectorAll(".sidebar,.vd-global-nav,.sidebar-toggle")].some(e=>e.checkVisibility())')
            if screen == 'records':
                check_menu_keyboard(['desktop-file-menu', 'desktop-tools-menu', 'desktop-help-menu'])
        if screen == 'settings':
            c.call('Emulation.setDeviceMetricsOverride', width=1200, height=800, deviceScaleFactor=1, mobile=False)
            c.evaluate('document.querySelector("[data-settings-tab=setup-local-models]").click()')
            c.evaluate('document.querySelector("#ollama-form").closest("details").scrollIntoView({block:"start"})')
            c.screenshot(out / 'settings-connection-1200x800.png')
            if not before:
                assert c.evaluate('!document.querySelector("#desktop-preparation").open')
                assert c.evaluate('!document.querySelector("#desktop-preparation").contains(document.querySelector("#preparation-status"))')
                # Preparation status and the active-operation stop stay outside the optional form.
                assert c.evaluate('!document.querySelector("#desktop-preparation").contains(document.querySelector("#prepare-selected-stop"))')
    c.call('Page.navigate', url=base+'/create?stage=source')
    wait_for(lambda: c.evaluate('location.pathname==="/create" && document.readyState==="complete" && !document.body.classList.contains("has-recording")'))
    capture('shared-new-record',1200,800)
    if not before:
        c.evaluate('document.querySelector("#desktop-tools-menu").open=true')
        assert c.evaluate('!document.querySelector("#open-connections").checkVisibility()')
        c.click('#desktop-tools-menu a')
        wait_for(lambda:c.evaluate('location.pathname==="/" && location.hash==="#settings" && !!document.querySelector("#local-provider")'))
        assert c.evaluate('[...document.querySelector("#local-provider").options].some(e=>e.value==="ollama")')
        assert c.evaluate('[...document.querySelector("#local-provider").options].some(e=>e.value==="lmstudio")')
        c.evaluate('document.querySelector("[data-settings-tab=setup-local-models]").click()')
        c.evaluate('document.querySelector("#ollama-form").closest("details").scrollIntoView({block:"start"})')
        capture('shared-connections',1200,800)
    c.call('Page.navigate', url=workspace)
    wait_for(lambda: c.evaluate('!!document.querySelector("#speech-feed .utterance")'))
    for width in [760, 375]:
        capture('narrow-recording', width, 800)
    (out / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'PASS: real UI visual captures and overflow/error assertions: {out}', flush=True)
