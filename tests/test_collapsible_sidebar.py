"""Focused static contract checks for the collapsible desktop sidebar."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / 'windows-app' / 'ui' / 'index.html'
LAYOUT = ROOT / 'windows-app' / 'ui' / 'layout.css'
APP_JS = ROOT / 'windows-app' / 'ui' / 'app.js'


def test_sidebar_toggle_markup_and_ids():
    html = INDEX.read_text(encoding='utf-8')
    assert '<div class="app-shell" id="app-shell">' in html
    assert '<aside class="sidebar" id="sidebar">' in html
    assert 'id="sidebar-toggle"' in html
    assert 'type="button"' in html
    assert 'class="vd-button vd-button--quiet sidebar-toggle"' in html
    assert 'aria-controls="sidebar"' in html
    assert 'aria-expanded="true"' in html
    assert 'aria-label=' in html
    assert '<svg viewBox="0 0 24 24" aria-hidden="true">' in html
    assert html.index('<button id="sidebar-toggle"') < html.index('<a href="#records" class="brand">')
    topbar = html.split('<header class="topbar">', 1)[1].split('</header>', 1)[0]
    assert 'sidebar-toggle' not in topbar


def test_sidebar_collapse_css_scoped_to_desktop_layout():
    css = LAYOUT.read_text(encoding='utf-8')
    desktop = css.split('@media(min-width:801px)', 1)[1]
    assert '.app-shell.sidebar-collapsed .sidebar{display:none}' in desktop
    assert '.app-shell>#sidebar-toggle{grid-column:1;grid-row:1;justify-self:start}' in css
    assert '.app-shell>.sidebar{grid-column:1;grid-row:2}' in css
    assert '.app-shell>.app-content{grid-column:2;grid-row:1/-1}' in css
    mobile = css.split('@media(max-width:800px)', 1)[1]
    assert '.sidebar-toggle{display:none}' in mobile
    assert '.app-shell{grid-template-columns:1fr}' in mobile
    surfaces = (ROOT / 'design-system' / 'surfaces.css').read_text(encoding='utf-8')
    assert 'body:has(>.vd-global-nav).sidebar-collapsed .vd-global-nav{display:none}' in surfaces
    assert 'body:has(>.vd-global-nav).sidebar-collapsed{max-width:var(--vd-content-width);padding-left:var(--vd-space-6)}' in surfaces
    desktop_surfaces = surfaces.split('@media(min-width:801px)', 1)[1]
    assert 'body>.sidebar-toggle{position:fixed;top:var(--vd-space-2);left:calc(var(--vd-nav-width) + var(--vd-space-2));z-index:var(--vd-layer-sticky)}' in desktop_surfaces
    assert 'body.sidebar-collapsed>.sidebar-toggle{left:var(--vd-space-2)}' in desktop_surfaces
    assert 'body>.sidebar-toggle svg{width:24px;height:24px;fill:none;stroke:currentColor' in desktop_surfaces
    mobile_surfaces = surfaces.split('@media(max-width:800px)', 1)[1]
    assert 'body>.sidebar-toggle{display:none}' in mobile_surfaces


def test_recording_workspace_toggle_contract():
    create = (ROOT / 'video_descriptor' / 'assets' / 'create.html').read_text(encoding='utf-8')
    assert 'id="sidebar-toggle"' in create
    assert 'aria-controls="sidebar"' in create
    assert create.index('<button id="sidebar-toggle"') < create.index('<nav class="vd-global-nav"')
    nav = create.split('<nav class="vd-global-nav"', 1)[1].split('</nav>', 1)[0]
    assert 'sidebar-toggle' not in nav
    studio = (ROOT / 'video_descriptor' / 'assets' / 'studio.js').read_text(encoding='utf-8')
    assert "const SIDEBAR_STORAGE_KEY='video-descriptor:ui:sidebar';" in studio
    assert 'document.body.classList.toggle(\'sidebar-collapsed\',collapsed);' in studio
    assert "collapsed?'Показать панель навигации':'Свернуть панель навигации'" in studio
    assert 'localStorage.getItem(SIDEBAR_STORAGE_KEY)' in studio
    assert 'localStorage.setItem(SIDEBAR_STORAGE_KEY' in studio


def test_sidebar_toggle_wired_with_persisted_state():
    js = APP_JS.read_text(encoding='utf-8')
    assert "$('sidebar-toggle').onclick=" in js
    assert "$('app-shell')" in js
    assert 'sidebar-collapsed' in js
    assert 'localStorage' in js
    assert 'document.body.classList.toggle' in js
    assert 'hashchange' in js
