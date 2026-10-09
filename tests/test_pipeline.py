import argparse
import json
from unittest.mock import Mock

import pytest

from video_descriptor.__main__ import cached_sources, positive
from video_descriptor.chapters import build_chapters
from video_descriptor.models import Note, Notes, Source, VideoSection
from video_descriptor.notes import filter_notes, group_sources, summarize
from video_descriptor.report import render


def test_unknown_model_sources_are_rejected(monkeypatch):
    response = Mock()
    event = {"done": True, "message": {"content": json.dumps({"notes": [{
        "title": "Test", "explanation": "Test", "steps": [], "limitations": [],
        "source_ids": ["invented"],
    }]})}}
    response.iter_lines.return_value = [json.dumps(event).encode()]
    monkeypatch.setattr("video_descriptor.notes.requests.post", Mock(return_value=response))
    with pytest.raises(ValueError, match="неизвестные источники"):
        summarize([Source(id="s1", start=0, end=1, text="test")], "model", "http://localhost")


def test_streamed_notes_are_assembled(monkeypatch):
    payload = json.dumps({"notes": [{"title": "AWS", "explanation": "Cloud",
                                     "steps": [], "limitations": [], "source_ids": ["s1"]}]})
    response = Mock()
    response.iter_lines.return_value = [json.dumps(event).encode() for event in [
        {"message": {"content": payload[:20]}, "done": False},
        {"message": {"content": payload[20:]}, "done": True},
    ]]
    post = Mock(return_value=response)
    monkeypatch.setattr("video_descriptor.notes.requests.post", post)
    notes = summarize([Source(id="s1", start=0, end=2, text="cloud")], "model", "http://local")
    assert notes.notes[0].source_ids == ["s1"]
    assert post.call_args.kwargs["json"]["stream"] is True
    response.close.assert_called_once()


def test_interrupted_ollama_stream_is_rejected(monkeypatch):
    responses = [Mock() for _ in range(3)]
    for response in responses:
        response.iter_lines.return_value = [b'{"message":{"content":"{\\"notes\\":[]}"}}']
    monkeypatch.setattr("video_descriptor.notes.requests.post",
                        Mock(side_effect=[responses[0], Mock(), responses[1], Mock(), responses[2]]))
    monkeypatch.setattr("video_descriptor.notes.time.sleep", lambda seconds: None)
    with pytest.raises(RuntimeError, match="оборвался"):
        summarize([Source(id="s1", start=0, end=2, text="cloud")], "model", "http://local")
    for response in responses:
        response.close.assert_called_once()


@pytest.mark.parametrize("selected", [[1], []])
def test_filter_keeps_only_selected_notes(monkeypatch, selected):
    candidates = Notes(notes=[
        Note(title="Расписание", explanation="Встреча в пятницу", steps=[], limitations=[],
             source_ids=["s1"]),
        Note(title="Клиент и сервер", explanation="Аналогия кофейни", steps=[], limitations=[],
             source_ids=["s2"]),
    ], sections=[VideoSection(kind="agenda", title="План лекции", items=["Compute"],
                              source_ids=["f1"])])
    response = Mock()
    event = {"done": True, "message": {"content": json.dumps({"keep": selected})}}
    response.iter_lines.return_value = [json.dumps(event).encode()]
    monkeypatch.setattr("video_descriptor.notes.requests.post", Mock(return_value=response))
    result = filter_notes(candidates, "model", "http://local")
    assert [note.title for note in result.notes] == [candidates.notes[index].title for index in selected]
    assert result.sections == candidates.sections
    if selected:
        assert result.notes[0].source_ids == ["s2"]


def test_chunking_preserves_absolute_timestamps():
    sources = [Source(id="s1", start=600, end=620, text="one"),
               Source(id="s2", start=780, end=800, text="two"),
               Source(id="f1", start=610, end=625, text="screen"),
               Source(id="f2", start=800, end=815, text="")]
    groups = group_sources(sources, 600, 180)
    assert [[source.id for source in group] for group in groups] == [["s1", "f1"], ["s2"]]
    assert groups[1][0].start == 780


def test_cached_transcription_does_not_reload_whisper(tmp_path):
    path = tmp_path / "transcript.json"
    path.write_text('[{"id":"s1","start":5,"end":8,"text":"speech"}]')
    produce = Mock(side_effect=AssertionError("Must use cache"))
    assert cached_sources(path, produce, Mock())[0].start == 5
    produce.assert_not_called()


def test_report_escapes_content_and_links_to_source_time(tmp_path):
    video = tmp_path / "clip with spaces.mp4"
    video.touch()
    folder = tmp_path / "report"
    folder.mkdir()
    source = Source(id="s1", start=613.5, end=620, text="<script>alert(1)</script>")
    note = Note(title="<b>AWS</b>", explanation="<script>x</script>", steps=[],
                limitations=[], source_ids=["s1"])
    render(folder, video, [source], [note])
    page = (folder / "report.html").read_text()
    assert '<button data-time="613.5">00:10:13' in page
    assert "&lt;script&gt;" in page
    assert "<script>alert(1)</script>" not in page
    assert "../clip%20with%20spaces.mp4" in page


def test_agenda_keeps_observed_times_and_merges_continuation():
    sources = [Source(id="f1", start=600, end=615, text="Agenda"),
               Source(id="f2", start=615, end=630, text="Compute, Storage")]
    sections = [VideoSection(kind="agenda", title="План", items=["Compute"], source_ids=["f1"]),
                VideoSection(kind="agenda", title="План", items=["Compute", "Storage"],
                             source_ids=["f2"])]
    chapters = build_chapters(sections, sources)
    assert len(chapters) == 1
    assert (chapters[0].start, chapters[0].end) == (600, 630)
    assert chapters[0].items == ["Compute", "Storage"]
    assert chapters[0].source_ids == ["f1", "f2"]


def test_section_with_unknown_source_is_rejected():
    section = VideoSection(kind="agenda", title="Plan", items=[], source_ids=["invented"])
    with pytest.raises(ValueError, match="неизвестные источники"):
        build_chapters([section], [])


def test_agenda_is_visible_even_when_all_notes_are_filtered(tmp_path):
    video = tmp_path / "video.mp4"
    source = Source(id="f1", start=600, end=615, text="Agenda", image="frames/f1.jpg")
    section = VideoSection(kind="agenda", title="План лекции", items=["Compute <AWS>"],
                           source_ids=["f1"])
    render(tmp_path, video, [source], [], build_chapters([section], [source]))
    page = (tmp_path / "report.html").read_text()
    assert 'aria-label="Разделы видео"' in page
    assert "Compute &lt;AWS&gt;" in page
    assert 'data-time="600.0"' in page
    assert "00:10:00–00:10:15" in page
    assert "Compute <AWS>" in (tmp_path / "notes.md").read_text()


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_invalid_sampling_interval(value):
    with pytest.raises(argparse.ArgumentTypeError):
        positive(value)
