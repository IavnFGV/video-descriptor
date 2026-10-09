import json
from unittest.mock import Mock

from video_descriptor.context import LectureContext
from video_descriptor.models import Notes, VideoSection
from video_descriptor.notes import chat_json
from video_descriptor.progress import ProgressLog


def result(summary="Discussed cloud resources", plan=None):
    return Notes(notes=[], sections=[VideoSection(kind="Topic", title="Cloud", items=[], source_ids=["s1"])],
                 context_summary=summary, lecture_plan=plan or [])


def test_history_is_bounded_and_reconstructed_identically_from_cache():
    context = LectureContext()
    cached = []
    for i in range(40):
        item = result(" ".join([f"block{i}"] * 40), ["Cloud basics", "Security"] if i == 0 else [])
        context.advance(item)
        cached.append(item.model_dump_json())
    history = context.snapshot()
    assert len(history["previous_block_summary"].split()) <= 20
    assert len(history["recent_summaries"]) == 5
    assert history["lecture_plan"] == ["Cloud basics", "Security"]
    recovered = LectureContext()
    for text in cached:
        recovered.advance(Notes.model_validate_json(text))
    assert recovered.snapshot() == history
    recovered.failed()
    assert recovered.snapshot()["previous_block_failed"] is True
    assert recovered.snapshot()["previous_block_summary"] == ""
    assert recovered.snapshot()["lecture_plan"] == history["lecture_plan"]


def test_every_analysis_request_contains_separate_context_and_current_evidence(monkeypatch):
    log = ProgressLog(lambda text: None, "lecture")
    log.lecture_context = LectureContext()
    log.lecture_context.advance(result(plan=["Cloud basics"]))
    response = Mock()
    response.iter_lines.return_value = [b'{"done":true,"message":{"content":"{}"}}']
    post = Mock(return_value=response)
    monkeypatch.setattr("video_descriptor.notes.requests.post", post)
    assert chat_json("instruction", {"sources": [{"id": "s2"}]}, {}, "model", "http://local", log) == "{}"
    payload = post.call_args.kwargs["json"]
    evidence = json.loads(payload["messages"][1]["content"])
    assert evidence["lecture_context"]["previous_block_summary"] == "Discussed cloud resources"
    assert evidence["lecture_context"]["lecture_plan"] == ["Cloud basics"]
    assert evidence["current_material"] == {"sources": [{"id": "s2"}]}
    assert "вторичный контекст" in payload["messages"][0]["content"]


def test_retry_does_not_nest_history_wrappers(monkeypatch):
    log = ProgressLog(lambda text: None, "lecture")
    log.lecture_context = LectureContext()
    first, second = Mock(), Mock()
    first.iter_lines.return_value = [b'{"done":true,"done_reason":"length","message":{"content":"partial"}}']
    second.iter_lines.return_value = [b'{"done":true,"message":{"content":"{}"}}']
    post = Mock(side_effect=[first, second])
    monkeypatch.setattr("video_descriptor.notes.requests.post", post)
    chat_json("instruction", {"sources": []}, {}, "model", "http://local", log)
    assert post.call_args_list[0].kwargs["json"]["messages"] == post.call_args_list[1].kwargs["json"]["messages"]
