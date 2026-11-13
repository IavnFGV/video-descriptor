"""Shared shell/asset contracts; actual layout, menus and dirty guards use Edge/CDP."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_shared_shell_is_loaded_on_all_full_page_surfaces():
    for name in ['video_descriptor/assets/create.html', 'windows-app/ui/index.html', 'video_descriptor/library.py', 'video_descriptor/report.py']:
        assert 'desktop-shell.js' in (ROOT / name).read_text(encoding='utf-8'), name
    shell = (ROOT / 'video_descriptor/assets/desktop-shell.js').read_text(encoding='utf-8')
    assert "get('embedded')==='1'" in shell  # never nested chrome in the iframe
    assert "help.body.append($('updates-check'))" in shell
    assert "file.body.append($('stop'))" in shell
    assert 'view.details.replaceWith(existing)' in shell  # same preferences/controller
    assert 'mayLeaveQuickReply' in shell and 'notesEditorDirty' in shell
    assert 'fetch(' not in shell
    assert '.cloneNode(' not in shell


def test_top_navigation_uses_shared_connections_and_view_on_every_surface():
    shell = (ROOT / 'video_descriptor/assets/desktop-shell.js').read_text(encoding='utf-8')
    assert "navigationItem(tools.body,'setup-open'" in shell
    assert "navigationItem(tools.body,'diagnostics-open'" in shell
    assert "$('open-connections').hidden=true" in shell
    assert "tools.body.append($('open-connections'))" not in shell
    assert 'data-sidebar-command' not in shell
    for name in ['windows-app/ui/index.html', 'video_descriptor/assets/create.html', 'video_descriptor/library.py', 'video_descriptor/report.py']:
        assert 'workspace-view.js' in (ROOT / name).read_text(encoding='utf-8'), name


def test_all_bundles_use_the_same_desktop_primitives():
    for name in ['windows-app/ui/app.css', 'video_descriptor/assets/create.css', 'video_descriptor/assets/editor.css']:
        css = (ROOT / name).read_text(encoding='utf-8')
        assert 'Source: design-system/desktop.css' in css
        assert '.desktop-header{' in css
        assert '.desktop-menu-content{' in css
    subprocess.run([sys.executable, 'scripts/build-ui-css.py', '--check'], cwd=ROOT, check=True, timeout=60)


def test_preparation_progress_and_stop_are_not_inside_optional_details():
    shell = (ROOT / 'video_descriptor/assets/desktop-shell.js').read_text(encoding='utf-8')
    assert "$('preparation-status')" in shell
    assert "card.insertBefore($('prepare-selected-stop'),preparation)" in shell
    assert "preparation.contains(document.activeElement)" in (ROOT / 'windows-app/ui/app.js').read_text(encoding='utf-8')


def test_material_tabs_share_the_settings_visual_primitive():
    html = (ROOT / 'video_descriptor/assets/create.html').read_text(encoding='utf-8')
    assert 'class="material-tabs vd-tabs" role="tablist"' in html
    css = (ROOT / 'design-system/workspace.css').read_text(encoding='utf-8')
    assert '.material-tabs button{flex:1}' in css
    assert '.material-tabs button[aria-selected' not in css


def test_settings_sections_are_real_tabs():
    shell = (ROOT / 'video_descriptor/assets/desktop-shell.js').read_text(encoding='utf-8')
    assert "index.className='desktop-settings-index vd-tabs'" in shell
    assert "index.setAttribute('role','tablist')" in shell
    assert "button.setAttribute('role','tab')" in shell
    assert "panel.setAttribute('role','tabpanel')" in shell
    assert "tabs[i].setAttribute('aria-selected',String(selected))" in shell
    assert "tabs[i].tabIndex=selected?0:-1" in shell
    assert "panel.hidden=!selected" in shell  # one section at a time
    assert 'window.desktopSettingsShow=' in shell
    assert "const panels=[card,...wizard.querySelectorAll(':scope>details')]" in shell
    assert "card.querySelector('h2').textContent='Функции и подготовка'" in shell
    for key in ["'ArrowRight'", "'ArrowLeft'", "'Home'", "'End'"]:
        assert key in shell
    html = (ROOT / 'windows-app/ui/index.html').read_text(encoding='utf-8')
    for section in ['setup-preparation', 'setup-card', 'setup-local-models', 'setup-cloud', 'setup-participants', 'setup-storage', 'setup-extra']:
        assert f'id="{section}"' in html, section
    assert '<summary>Локальный AI</summary>' in html
    app = (ROOT / 'windows-app/ui/app.js').read_text(encoding='utf-8')
    assert 'function revealSettingsField' in app
    assert app.count('revealSettingsField(') >= 6  # every settings focus path reveals its panel
    assert 'target.closest(\'details\').open=true' not in app
