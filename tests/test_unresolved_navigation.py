"""Clickable navigation to unresolved speech intervals in the shared transcript panel."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CREATE_JS = ROOT / 'video_descriptor' / 'assets' / 'create.js'
SURFACES = ROOT / 'design-system' / 'surfaces.css'


def test_unresolved_intervals_are_clickable_in_the_transcript():
    """The production counter renders one link per interval and navigates to it."""
    node = shutil.which('node')
    assert node, 'Node.js is required for the shared workspace check.'
    subprocess.run([node, 'tests/unresolved_navigation.cjs'], cwd=ROOT, check=True, timeout=30)


def test_transcript_marks_every_unresolved_interval():
    source = CREATE_JS.read_text(encoding='utf-8')
    # Each unresolved row carries its interval id, so a link can address exactly one interval.
    assert 'row.dataset.gapId=gap.id;' in source
    assert "querySelectorAll('[data-gap-id]')" in source
    # The counter is rebuilt only when the snapshot changes, so polling keeps the focused link.
    assert "changed('speech-count'" in source
    assert "paintSpeechCount(snapshot, node)" in source


def test_navigation_styles_are_shared_and_bundled():
    surfaces = SURFACES.read_text(encoding='utf-8')
    assert '.counter .gap-link{' in surfaces
    assert '.unresolved-interval.current{' in surfaces
    for bundle in ('video_descriptor/assets/create.css', 'video_descriptor/assets/editor.css'):
        css = (ROOT / bundle).read_text(encoding='utf-8')
        assert '.counter .gap-link{' in css, bundle
        assert '.unresolved-interval.current{' in css, bundle
    subprocess.run([sys.executable, 'scripts/build-ui-css.py', '--check'], cwd=ROOT, check=True, timeout=60)
