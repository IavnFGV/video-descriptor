import json

import pytest

from video_descriptor.models import Source
from video_descriptor.report import render
from video_descriptor.translate import refresh_reports, translate_batch


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


@pytest.mark.parametrize("segments", [[], [{"id": "unknown", "text": "translation"}],
                                      [{"id": "s1", "text": ""}],
                                      [{"id": "s1", "text": "one"},
                                       {"id": "s1", "text": "two"}]])
def test_translation_cannot_drop_or_duplicate_subtitle_segments(monkeypatch, segments):
    monkeypatch.setattr("video_descriptor.translate.chat_json", lambda *a, **kw:
                        json.dumps({"segments": segments}))
    with pytest.raises(ValueError, match="каждый исходный ID"):
        translate_batch([Source(id="s1", start=0, end=1, text="hello")], "model", "url")


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
