import json

import pytest

from video_descriptor.models import Source
from video_descriptor.report import render
from video_descriptor.translate import refresh_reports, translate_batch


def test_bilingual_editor_split_exports_and_report_preserve_later_ids(tmp_path):
    from video_descriptor.speech import edit_utterance, state
    from video_descriptor.subtitles import webvtt
    folder = tmp_path / 'output' / 'english'
    folder.mkdir(parents=True)
    original = [dict(id='s1', start=0, end=4, text='Hello. Goodbye.'),
                dict(id='s2', start=4, end=6, text='Next.')]
    for name, value in {
        'transcript.json': original, 'translations.json': {'s1': 'Привет. Пока.', 's2': 'Далее.'},
        'manifest.json': {'video': str(tmp_path / 'video.mp4')},
        'frames.json': [], 'notes.json': {'notes': [], 'sections': []},
    }.items():
        (folder / name).write_text(json.dumps(value))
    result = state(tmp_path, {'folder': ['english']})['result']
    saved = edit_utterance(tmp_path, dict(folder='english', revision=result['edit_revision'],
                          index=0, action='split', at=2, text='Hello.', right_text='Goodbye.',
                          speaker='unknown', right_speaker='unknown'))
    second_id = saved['segments'][1]['id']
    assert saved['translations']['s1'] == 'Привет. Пока.'
    assert saved['translations'][second_id] == ''
    assert saved['segments'][2]['id'] == 's2'
    assert saved['translations']['s2'] == 'Далее.'
    edited = edit_utterance(tmp_path, dict(folder='english', revision=saved['edit_revision'],
                           index=0, action='edit', text='Hello!', speaker='unknown', translation='Привет!'))
    edited = edit_utterance(tmp_path, dict(folder='english', revision=edited['edit_revision'],
                           index=1, action='edit', text='Goodbye.', speaker='unknown', translation='Пока.'))
    assert 'Hello!' in webvtt(edited)
    assert '00:00:02.000 --> 00:00:04.000\nПока.' in webvtt(edited, 'ru')
    assert (folder / 'original.vtt').read_text() == webvtt(edited)
    assert (folder / 'ru.vtt').read_text() == webvtt(edited, 'ru')
    assert 'Hello!' in (folder / 'report.html').read_text()
    assert 'Привет!' in (folder / 'report.html').read_text()
    assert json.loads((folder / 'transcript.json').read_text()) == original
    assert json.loads((folder / 'translations.json').read_text())['s1'] == 'Привет. Пока.'
    with pytest.raises(ValueError, match='изменились'):
        edit_utterance(tmp_path, dict(folder='english', revision=saved['edit_revision'],
                       index=0, action='edit', text='Stale', speaker='unknown'))


def test_subtitle_timestamps_translation_and_escaped_markup(tmp_path):
    sources = [Source(id="s1", start=1900.123, end=1902.456, text="<script> & hello"),
               Source(id="f1", start=1900, end=1910, text="OCR", image="frame.jpg")]
    render(tmp_path, tmp_path / "video.mp4", sources, [], translations={"s1": "Привет <b>"})
    original = (tmp_path / "original.vtt").read_text()
    russian = (tmp_path / "ru.vtt").read_text()
    assert "00:31:40.123 --> 00:31:42.456" in original
    assert "00:31:40.123 --> 00:31:42.456" in russian
    assert "OCR" not in original
    assert "&lt;script&gt; &amp; hello" in original
    page = (tmp_path / "report.html").read_text()
    assert 'src="ru.vtt"' in page
    assert 'data-start="1900.123" data-end="1902.456"' in page
    assert "Привет &lt;b&gt;" in page


@pytest.mark.parametrize("answer", ["", "[[s0002]]\nПривет", "[[s0001]]\n",
                                     "[[s0001]]\nОдин\n[[s0001]]\nДва"])
def test_translation_cannot_drop_or_duplicate_subtitle_segments(monkeypatch, answer):
    monkeypatch.setattr("video_descriptor.translate.chat_json", lambda *a, **kw: answer)
    with pytest.raises(ValueError, match="каждую исходную метку"):
        translate_batch([Source(id="s1", start=0, end=1, text="hello")], "model", "url")


def test_marker_translation_allows_merge_without_shifting_ids(monkeypatch, tmp_path):
    sources = [Source(id=f"s{i}", start=i, end=i + 1, text="hello") for i in range(3)]
    monkeypatch.setattr("video_descriptor.translate.chat_json", lambda *a, **kw:
                        "[[s0001]]\nОбъединённый перевод\n[[s0002]]\n[[s0003]]\nСледующий")
    translated = translate_batch(sources, "model", "url")
    assert translated == {"s0": "Объединённый перевод", "s1": "", "s2": "Следующий"}
    render(tmp_path, tmp_path / "video.mp4", sources, [], translations=translated)
    vtt = (tmp_path / "ru.vtt").read_text()
    assert "00:00:00.000 --> 00:00:02.000" in vtt
    assert "00:00:02.000 --> 00:00:03.000" in vtt


def test_marker_failure_splits_and_recovers(monkeypatch):
    from video_descriptor.translate import translate_resilient
    def answer(prompt, text, schema, *args, **kwargs):
        assert schema is None
        return "wrong" if "[[s0002]]" in text else "[[s0001]]\nПеревод"
    monkeypatch.setattr("video_descriptor.translate.chat_json", answer)
    sources = [Source(id=f"s{i}", start=i, end=i + 1, text="hello") for i in range(2)]
    assert translate_resilient(sources, "model", "url") == {"s0": "Перевод", "s1": "Перевод"}


def test_refresh_old_report_preserves_manual_markdown_edits(tmp_path):
    for name, value in {
        "manifest.json": {"video": str(tmp_path / "video.mp4")},
        "transcript.json": [{"id": "s1", "start": 0, "end": 1, "text": "hello"}],
        "frames.json": [], "notes.json": {"notes": [], "sections": []},
    }.items():
        (tmp_path / name).write_text(json.dumps(value))
    (tmp_path / "notes.md").write_text("My manual additions")
    refresh_reports(tmp_path, {"s1": "Привет"})
    assert (tmp_path / "notes.md").read_text() == "My manual additions"
    assert "Привет" in (tmp_path / "report.html").read_text()
