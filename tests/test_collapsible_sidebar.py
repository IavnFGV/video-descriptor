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
    assert '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/><path d="m16 15-3-3 3-3"/>' in html
    assert 'M9 5l7' not in html
    shell_children = html.split('<div class="app-shell" id="app-shell">', 1)[1].split('<header class="topbar">', 1)[0]
    assert 'sidebar-toggle' not in shell_children
    topbar = html.split('<header class="topbar">', 1)[1].split('</header>', 1)[0]
    assert topbar.index('<button id="sidebar-toggle"') < topbar.index('<p>Video Descriptor')


def test_sidebar_collapse_css_scoped_to_desktop_layout():
    css = LAYOUT.read_text(encoding='utf-8')
    desktop = css.split('@media(min-width:801px)', 1)[1]
    assert '.app-shell.sidebar-collapsed{grid-template-columns:minmax(0,1fr)}' in desktop
    assert '.app-shell.sidebar-collapsed>.app-content{grid-column:1}' in desktop
    assert '.app-shell.sidebar-collapsed .sidebar{display:none}' in desktop
    assert '.app-shell>.sidebar{grid-column:1;grid-row:1}' in css
    assert '.app-shell>.app-content{grid-column:2;grid-row:1}' in css
    assert '.topbar .sidebar-toggle{flex-shrink:0}' in css
    mobile = css.split('@media(max-width:800px)', 1)[1]
    assert '.sidebar-toggle{display:none}' in mobile
    assert '.app-shell{grid-template-columns:1fr}' in mobile
    assert '.app-shell>.app-content{grid-column:1;grid-row:2}' in mobile
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
    assert "sidebarToggle.querySelector('svg').innerHTML=collapsed?SIDEBAR_TOGGLE_ICONS.open:SIDEBAR_TOGGLE_ICONS.close;" in studio
    assert '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/><path d="m16 15-3-3 3-3"/>' in create
    assert 'M9 5l7' not in create and 'M9 5l7' not in studio


def test_sidebar_toggle_wired_with_persisted_state():
    js = APP_JS.read_text(encoding='utf-8')
    assert "$('sidebar-toggle').onclick=" in js
    assert "$('app-shell')" in js
    assert 'sidebar-collapsed' in js
    assert 'localStorage' in js
    assert 'document.body.classList.toggle' in js
    assert 'hashchange' in js
    assert "open:'<rect width=\"18\" height=\"18\" x=\"3\" y=\"3\" rx=\"2\"/><path d=\"M9 3v18\"/><path d=\"m14 9 3 3-3 3\"/>'" in js
    assert "close:'<rect width=\"18\" height=\"18\" x=\"3\" y=\"3\" rx=\"2\"/><path d=\"M9 3v18\"/><path d=\"m16 15-3-3 3-3\"/>'" in js
    assert "toggle.querySelector('svg').innerHTML=collapsed?SIDEBAR_TOGGLE_ICONS.open:SIDEBAR_TOGGLE_ICONS.close;" in js
    assert 'M9 5l7' not in js
