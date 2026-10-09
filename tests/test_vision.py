import base64
import json
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from video_descriptor.chapters import build_chapters
from video_descriptor.models import Notes, Quiz, QuizOption, Source, VideoSection
from video_descriptor.notes import explain_quizzes, plan_vision, summarize
from video_descriptor.report import render
from video_descriptor.vision import encode_frames, frame_changes


def response(content):
    result = Mock()
    result.iter_lines.return_value = [json.dumps({"done": True, "message": {
        "content": json.dumps(content)
    }}).encode()]
    return result


def test_requested_image_really_replaces_its_ocr_in_api_payload(tmp_path, monkeypatch):
    path = tmp_path / "frame.jpg"
    cv2.imwrite(str(path), np.zeros((200, 400, 3), dtype=np.uint8))
    source = Source(id="f1", start=0, end=15, text="OCR should not duplicate image", image=path.name)
    images, metadata = encode_frames([source], ["f1"], tmp_path, 200)
    decoded = cv2.imdecode(np.frombuffer(base64.b64decode(images[0]), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[:2] == (100, 200)
    post = Mock(return_value=response({"notes": [], "sections": []}))
    monkeypatch.setattr("video_descriptor.notes.requests.post", post)
    summarize([source], "model", "http://local", images=images, image_sources=metadata)
    message = post.call_args.kwargs["json"]["messages"][1]
    assert message["images"] == images
    evidence = json.loads(message["content"])
    assert evidence["image_sources"][0]["id"] == "f1"
    assert evidence["sources"][0]["text"] == ""


@pytest.mark.parametrize("ids", [["s1"], ["invented"], ["f1", "f1", "f1"]])
def test_router_rejects_non_frame_ids_and_over_budget(ids, monkeypatch):
    monkeypatch.setattr("video_descriptor.notes.requests.post", Mock(return_value=response({
        "frame_ids": ids, "reason": "inspect"
    })))
    sources = [Source(id="s1", start=0, end=10, text="speech"),
               Source(id="f1", start=0, end=15, text="quiz", image="frame.jpg")]
    with pytest.raises(ValueError, match="неизвестные кадры"):
        plan_vision(sources, {}, "model", "http://local", 2)


def test_pixel_changes_notice_highlighting_even_when_ocr_is_identical(tmp_path):
    first = np.full((144, 256, 3), 255, dtype=np.uint8)
    second = first.copy()
    second[70:80, 40:210] = (0, 180, 0)
    cv2.imwrite(str(tmp_path / "a.jpg"), first)
    cv2.imwrite(str(tmp_path / "b.jpg"), second)
    sources = [Source(id="f1", start=0, end=15, text="A B C D", image="a.jpg"),
               Source(id="f2", start=15, end=30, text="A B C D", image="b.jpg")]
    assert frame_changes(sources, tmp_path)["f2"] > 0


def test_quiz_question_and_answer_across_blocks_merge_and_render(tmp_path):
    options = [QuizOption(label="A", text="one"), QuizOption(label="B", text="two")]
    question = Quiz(question="Which option?", options=options, correct_option=None, explanation="")
    answered = question.model_copy(update={"correct_option": "B", "explanation": "Speaker explains"})
    sources = [Source(id="f1", start=165, end=180, text="question"),
               Source(id="f2", start=200, end=215, text="answer")]
    sections = [VideoSection(kind="Knowledge check", title="Question", items=[],
                             source_ids=["f1"], quiz=question),
                VideoSection(kind="Answer discussion", title="Answer", items=[],
                             source_ids=["f2"], quiz=answered)]
    chapters = build_chapters(sections, sources)
    assert len(chapters) == 1
    assert chapters[0].quiz.correct_option == "B"
    assert chapters[0].end == 215
    render(tmp_path, tmp_path / "video.mp4", sources, [], chapters)
    page = (tmp_path / "report.html").read_text()
    assert '<li class="correct">B: two</li>' in page
    assert "Speaker explains" in page


def test_unsupported_answer_is_rejected():
    with pytest.raises(ValueError, match="меткой существующего варианта"):
        Quiz(question="Question", options=[QuizOption(label="A", text="one")],
             correct_option="D", explanation="")


def test_quiz_explanation_uses_speech_and_preserves_unknown_answer(monkeypatch):
    notes = Notes(notes=[], sections=[VideoSection(
        kind="quiz", title="Question", items=[], source_ids=["f1"],
        quiz=Quiz(question="First?", options=[], correct_option=None, explanation=""),
    )])
    sources = [Source(id="f1", start=0, end=15, text="slide", image="frame.jpg"),
               Source(id="s1", start=20, end=25, text="Speaker caveat")]
    def reply(prompt, evidence, schema, *args, **kwargs):
        assert [item["id"] for item in evidence["speech"]] == ["s1"]
        return json.dumps({"explanations": [{"question": "First?",
                           "explanation": "Speaker caveat", "source_ids": ["s1"]}]})
    monkeypatch.setattr("video_descriptor.notes.chat_json", reply)
    result = explain_quizzes(notes, sources, "model", "url")
    assert result.sections[0].quiz.correct_option is None
    assert result.sections[0].quiz.explanation == "Speaker caveat"
    assert result.sections[0].source_ids == ["f1", "s1"]
    assert notes.sections[0].quiz.explanation == ""


def test_different_questions_with_same_section_title_remain_separate():
    sources = [Source(id="f1", start=0, end=15, text="question"),
               Source(id="f2", start=15, end=30, text="next question")]
    sections = [VideoSection(kind="Quiz", title="Knowledge check", items=[], source_ids=[key],
                             quiz=Quiz(question=question, options=[], correct_option=None,
                                       explanation=""))
                for key, question in [("f1", "First?"), ("f2", "Second?")]]
    assert len(build_chapters(sections, sources)) == 2


def test_section_type_is_chosen_by_model_without_fixed_enum():
    section = VideoSection(kind="Разбор архитектурной схемы", title="Flow", items=[],
                           source_ids=["f1"])
    assert section.kind == "Разбор архитектурной схемы"
