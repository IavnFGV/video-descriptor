"""Offline contract checks; real geometry/editor scenarios use the Edge fixture harness."""
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_preferences_node():
    node = shutil.which('node')
    assert node, 'Node.js is required for workspace preference tests'
    subprocess.run([node, 'tests/workspace_view.cjs'], cwd=ROOT, check=True, timeout=30)


def test_workspace_assets_and_critical_controls():
    html = (ROOT / 'video_descriptor/assets/create.html').read_text(encoding='utf-8')
    assert html.index('/studio-assets/workspace-view.js') < html.index('<body')
    # The library shell has no recording panels; common chrome handles its View commands.
    assert '/studio-assets/workspace-view.js' not in (ROOT / 'windows-app/ui/index.html').read_text(encoding='utf-8')
    serve = (ROOT / 'video_descriptor/serve.py').read_text(encoding='utf-8')
    assert "'workspace-view.js'" in serve
    source = (ROOT / 'video_descriptor/assets/recording.js').read_text(encoding='utf-8')
    assert 'workspace.append(speechHeading)' in source
    assert "workspace.append($('errors-card'))" in source
    assert "workspace.append($('speaker-notice'))" in source
    assert "['translation-summary','translation-blocks-panel']" in source
    css = (ROOT / 'design-system/workspace.css').read_text(encoding='utf-8')
    for key in ['video', 'transcript', 'speakers', 'translation', 'notes', 'article', 'technical']:
        assert f'data-view-{key}=false' in css
    assert '@media(max-width:1000px)' in css
    assert 'workspace-view-empty' in css
    # Existing controller is adopted by common chrome, without another state owner.
    assert '.vd-global-nav>.workspace-view-menu>summary{' in css  # fallback without chrome
    module = (ROOT / 'video_descriptor/assets/workspace-view.js').read_text(encoding='utf-8')
    assert "document.querySelector('.vd-global-nav')" in module
    assert ".topbar" not in module
    shell = (ROOT / 'video_descriptor/assets/desktop-shell.js').read_text(encoding='utf-8')
    assert 'view.details.replaceWith(existing)' in shell
    surfaces = (ROOT / 'design-system/surfaces.css').read_text(encoding='utf-8')
    assert 'input:not([type=checkbox]):not([type=radio])' in surfaces


def test_visibility_module_has_no_processing_side_effects():
    source = (ROOT / 'video_descriptor/assets/workspace-view.js').read_text(encoding='utf-8')
    for forbidden in ['fetch(', 'innerHTML', 'replaceChildren', '.remove()', 'notesEditorDirty', 'currentTime=', 'location.href=']:
        assert forbidden not in source
