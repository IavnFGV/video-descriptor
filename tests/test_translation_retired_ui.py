"""Retired UI must not silently start translation through historical drafts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_both_native_notes_entry_points_explicitly_disable_translation():
    for name in ['video_descriptor/assets/construction.js', 'windows-app/ui/app.js']:
        source = (ROOT / name).read_text(encoding='utf-8')
        assert 'translate_after:false' in source
        assert "translate_after:$('translate-after').checked" not in source
        assert "translate_after:$('notes-translate-after').checked" not in source


def test_retired_checkboxes_are_not_restorable_controls():
    for name, control in [('video_descriptor/assets/create.html', 'construction-translate-after'),
                          ('windows-app/ui/index.html', 'notes-translate-after')]:
        source = (ROOT / name).read_text(encoding='utf-8')
        assert f'id="{control}" type="hidden"' in source


def test_retired_prompt_drafts_are_kept_but_not_offered():
    source = (ROOT / 'video_descriptor/assets/create.js').read_text(encoding='utf-8')
    assert ".filter(([task])=>task!=='translate')" in source
    from video_descriptor import prompt_settings
    assert 'translate' in prompt_settings.defaults()
