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


def test_sidebar_collapse_css_scoped_to_desktop_layout():
    css = LAYOUT.read_text(encoding='utf-8')
    desktop = css.split('@media(min-width:801px)', 1)[1]
    assert '.app-shell.sidebar-collapsed{grid-template-columns:0 minmax(0,1fr)}' in desktop
    assert '.app-shell.sidebar-collapsed .sidebar{display:none}' in desktop
    mobile = css.split('@media(max-width:800px)', 1)[1]
    assert '.sidebar-toggle{display:none}' in mobile
    assert '.app-shell{grid-template-columns:1fr}' in mobile


def test_sidebar_toggle_wired_with_persisted_state():
    js = APP_JS.read_text(encoding='utf-8')
    assert "$('sidebar-toggle').onclick=" in js
    assert "$('app-shell')" in js
    assert 'sidebar-collapsed' in js
    assert 'localStorage' in js
    assert 'hashchange' in js
