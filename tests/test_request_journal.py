import json
import sys
from unittest.mock import Mock

import pytest

from video_descriptor.notes import chat_json
from video_descriptor.progress import ProgressLog


def test_exact_payload_and_partial_response_survive_bad_stream(tmp_path, monkeypatch):
    log = ProgressLog(lambda message: None, "lecture.mp4", tmp_path / "requests")
    log.update(chunk="5/18", stage="4/5")
    response = Mock()
    response.iter_lines.return_value = [
        b'{"message":{"content":"partial","thinking":"reason"}}', b'broken JSON',
    ]
    post = Mock(return_value=response)
    monkeypatch.setattr("video_descriptor.notes.requests.post", post)
    with pytest.raises(ValueError):
        chat_json("instruction", {"text": "speech"}, {}, "model", "http://local", log,
                  images=["image-base64"])
    folder = next((tmp_path / "requests").iterdir())
    request = json.loads((folder / "request.json").read_text())
    assert request["payload"] == post.call_args.kwargs["json"]
    assert request["context"]["chunk"] == "5/18"
    assert (folder / "response.txt").read_text() == "partial"
    assert (folder / "thinking.txt").read_text() == "reason"
    assert "broken JSON" in (folder / "events.jsonl").read_text()
    assert json.loads((folder / "result.json").read_text())["status"] == "error"
    response.close.assert_called_once()


@pytest.mark.parametrize("with_context", [False, True])
@pytest.mark.parametrize("reuse_completed", [False, True])
def test_failed_block_does_not_stop_next_and_retry_reuses_success(tmp_path, monkeypatch, with_context, reuse_completed):
    from video_descriptor import __main__ as cli
    from video_descriptor.models import Note, Notes, Source

    monkeypatch.chdir(tmp_path)
    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr("sys.argv", ["video_descriptor", str(video), "--model", "model",
                                     "--vision", "off", "--frame-strategy", "interval",
                                     *([] if with_context else ["--without-context"])])
    monkeypatch.setattr(cli, "probe", lambda path: {
        "format": {"duration": "360"}, "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
    })
    monkeypatch.setattr(cli, "extract_audio", lambda video, audio, start, duration: audio.write_bytes(b"audio"))
    speech = [Source(id="s1", start=0, end=5, text="first"),
              Source(id="s2", start=180, end=185, text="second")]
    monkeypatch.setattr(cli, "transcribe", lambda *args: speech)
    monkeypatch.setattr(cli, "extract_frames", lambda *args, **kwargs: [])
    calls = []
    def summarize(group, *args, **kwargs):
        calls.append(group[0].id)
        if group[0].id == "s1":
            raise RuntimeError("model output length")
        return Notes(notes=[Note(title="Second", explanation="Known", steps=[], limitations=[],
                                 source_ids=[group[0].id])])
    monkeypatch.setattr(cli, "summarize", summarize)
    monkeypatch.setattr(cli, "filter_notes", lambda result, *args: result)
    assert cli.main() == 0
    folder = next((tmp_path / "output").iterdir())
    assert calls == ["s1", "s2"]
    assert json.loads((folder / "analysis-errors.json").read_text())[0]["block"] == 1
    assert "Конспект неполный" in (folder / "report.html").read_text()
    assert "Second" in (folder / "notes.md").read_text()

    calls.clear()
    def repaired(group, *args, **kwargs):
        calls.append(group[0].id)
        return Notes(notes=[Note(title="Repaired", explanation="Known", steps=[], limitations=[],
                                 source_ids=[group[0].id])])
    monkeypatch.setattr(cli, "summarize", repaired)
    if reuse_completed:
        monkeypatch.setattr("sys.argv", sys.argv + ["--reuse-completed-blocks"])
    assert cli.main() == 0
    assert calls == (["s1", "s2"] if with_context and not reuse_completed else ["s1"])
    assert json.loads((folder / "analysis-errors.json").read_text()) == []
    assert "Конспект неполный" not in (folder / "report.html").read_text()
    assert len(json.loads((folder / "notes.json").read_text())["notes"]) == 2


def test_runner_failure_reloads_and_retries_exact_request_with_bounded_attempts(monkeypatch):
    from video_descriptor import notes
    once = Mock(side_effect=[RuntimeError("Ollama HTTP 500: runner crashed"), "{}"])
    monkeypatch.setattr(notes, "_chat_json_once", once)
    reset = Mock()
    monkeypatch.setattr(notes.requests, "post", reset)
    monkeypatch.setattr(notes.time, "sleep", lambda seconds: None)
    assert chat_json("prompt", {"speech": "hello"}, {}, "model", "http://local", images=["image"]) == "{}"
    assert once.call_args_list[0] == once.call_args_list[1]
    assert reset.call_args.kwargs["json"] == {"model": "model", "keep_alive": 0}
    once.reset_mock()
    once.side_effect = RuntimeError("Ollama HTTP 500: runner crashed")
    with pytest.raises(RuntimeError, match="500"):
        chat_json("prompt", [], {}, "model", "http://local")
    assert once.call_count == 3
    once.reset_mock()
    once.side_effect = RuntimeError("Ollama: ответ достиг лимита 8192")
    with pytest.raises(RuntimeError, match="8192"):
        chat_json("prompt", [], {}, "model", "http://local")
    assert once.call_count == 1


def test_analysis_tasks_keep_same_context_to_avoid_runner_reload(monkeypatch):
    response = Mock()
    response.iter_lines.return_value = [b'{"done":true,"message":{"content":"{}"}}']
    post = Mock(return_value=response)
    monkeypatch.setattr("video_descriptor.notes.requests.post", post)
    for task, context, limit in [("route", 16384, 4096), ("filter", 8192, 4096),
                                 ("filter", 8192, 8192), ("quiz_explanation", 8192, 4096)]:
        chat_json("prompt", [], {}, "model", "http://local", task=task,
                  context=context, output_limit=limit)
        assert post.call_args.kwargs["json"]["options"]["num_ctx"] == 16384


@pytest.mark.parametrize("initial_thinking", [False, True])
def test_switching_thinking_reuses_completed_blocks_and_only_calls_pending_block(tmp_path, monkeypatch, initial_thinking):
    from video_descriptor import __main__ as cli
    from video_descriptor.models import Note, Notes, Source

    monkeypatch.chdir(tmp_path)
    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"video")
    argv = ["video_descriptor", str(video), "--model", "model", "--vision", "off",
            "--frame-strategy", "interval"]
    monkeypatch.setattr("sys.argv", argv + (["--think"] if initial_thinking else []))
    monkeypatch.setattr(cli, "probe", lambda path: {
        "format": {"duration": "360"}, "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
    })
    extract = Mock(side_effect=lambda video, audio, start, duration: audio.write_bytes(b"audio"))
    speech = [Source(id="s1", start=0, end=5, text="first"),
              Source(id="s2", start=180, end=185, text="second")]
    transcribe = Mock(return_value=speech)
    frames = Mock(return_value=[])
    monkeypatch.setattr(cli, "extract_audio", extract)
    monkeypatch.setattr(cli, "transcribe", transcribe)
    monkeypatch.setattr(cli, "extract_frames", frames)
    calls = []
    def produce(group, model, url, log, **kwargs):
        calls.append((group[0].id, log.thinking_enabled))
        if group[0].id == "s2":
            raise KeyboardInterrupt
        return Notes(notes=[Note(title="First", explanation="Known", steps=[], limitations=[],
                                 source_ids=["s1"])], context_summary="First block explained")
    filter_call = Mock(side_effect=lambda result, *args: result)
    monkeypatch.setattr(cli, "summarize", produce)
    monkeypatch.setattr(cli, "filter_notes", filter_call)
    assert cli.main() == 130
    folder = next((tmp_path / "output").iterdir())
    saved = {p.name: p.read_bytes() for p in folder.glob("notes-*-????.json")}
    assert len(saved) == 1
    calls.clear()
    def resumed(group, model, url, log, **kwargs):
        calls.append((group[0].id, log.thinking_enabled))
        assert log.lecture_context.snapshot()["previous_block_summary"] == "First block explained"
        return Notes(notes=[Note(title="Second", explanation="Known", steps=[], limitations=[],
                                 source_ids=[group[0].id])])
    monkeypatch.setattr(cli, "summarize", resumed)
    monkeypatch.setattr("sys.argv", argv + ([] if initial_thinking else ["--think"]))
    assert cli.main() == 0
    assert calls == [("s2", not initial_thinking)]
    assert filter_call.call_count == 2  # One completed filter reused; only second block is new.
    extract.assert_called_once()
    transcribe.assert_called_once()
    frames.assert_called_once()
    for name, data in saved.items():
        assert (folder / name).read_bytes() == data
    assert len(json.loads((folder / "notes.json").read_text())["notes"]) == 2


def test_merge_remaining_slides_preserves_old_completed_cache(tmp_path, monkeypatch):
    from video_descriptor import __main__ as cli
    from video_descriptor.models import Note, Notes, Source

    monkeypatch.chdir(tmp_path)
    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"video")
    argv = ["video_descriptor", str(video), "--model", "model", "--vision", "off",
            "--chunk-strategy", "slides"]
    monkeypatch.setattr("sys.argv", argv + ["--min-chunk-seconds", "0"])
    monkeypatch.setattr(cli, "probe", lambda path: {
        "format": {"duration": "240"}, "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]})
    monkeypatch.setattr(cli, "extract_audio", lambda video, audio, start, duration: audio.write_bytes(b"audio"))
    speech = [Source(id=f"s{i}", start=i * 60 + 1, end=i * 60 + 10, text=f"speech {i}") for i in range(3)]
    frames = [Source(id=f"f{i}", start=i * 60, end=(i + 1) * 60,
                     text=" ".join(f"topic{i}word{j}" for j in range(8)), image=f"slide{i}.jpg") for i in range(3)]
    monkeypatch.setattr(cli, "transcribe", lambda *args: speech)
    monkeypatch.setattr(cli, "extract_frames", lambda *args, **kwargs: frames)
    monkeypatch.setattr(cli, "frame_changes", lambda *args: {})
    def produce(group, *args, **kwargs):
        if any(s.id == "s1" for s in group):
            raise KeyboardInterrupt
        return Notes(notes=[Note(title="First", explanation="Known", steps=[], limitations=[], source_ids=["s0"])],
                     context_summary="First summary")
    monkeypatch.setattr(cli, "summarize", produce)
    filter_call = Mock(side_effect=lambda result, *args: result)
    monkeypatch.setattr(cli, "filter_notes", filter_call)
    assert cli.main() == 130
    folder = next((tmp_path / "output").iterdir())
    original = next(folder.glob("notes-*-0001.json"))
    original_bytes = original.read_bytes()
    calls = []
    def resumed(group, model, url, log, **kwargs):
        calls.append([s.id for s in group if not s.image])
        assert log.lecture_context.previous == "First summary"
        assert len(kwargs["slide_segments"]) == 2
        return Notes(notes=[Note(title="Merged", explanation="Known", steps=[], limitations=[], source_ids=["s1", "s2"])])
    monkeypatch.setattr(cli, "summarize", resumed)
    monkeypatch.setattr("sys.argv", argv + ["--min-chunk-seconds", "180", "--preserve-blocks", "1",
                                          "--reuse-completed-blocks"])
    assert cli.main() == 0
    assert calls == [["s1", "s2"]]
    assert filter_call.call_count == 2
    assert original.read_bytes() == original_bytes
    assert json.loads((folder / "notes-live.json").read_text())["total_blocks"] == 2
