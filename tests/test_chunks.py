from video_descriptor.chunks import merge_short_groups, slide_groups
from video_descriptor.models import Source


def source(id, start, text, image=None):
    return Source(id=id, start=start, end=start + 10, text=text, image=image)


def test_slide_boundary_keeps_speech_and_ignores_repeated_slide():
    text = "What is cloud computing on demand delivery of IT resources"
    sources = [source("f1", 0, text, "first.jpg"),
               source("s1", 170, "still explaining first slide"),
               source("f2", 180, text, "first-highlighted.jpg"),
               source("s2", 190, "answer explanation"),
               source("f3", 250, "Regional availability zones connect separate isolated data centers", "second.jpg"),
               source("s3", 260, "new slide explanation")]
    groups, plan = slide_groups(sources, 0, 300, {"f2": 0.8, "f3": 0.8})
    assert [[s.id for s in group] for group in groups] == [["f1", "s1", "f2", "s2"], ["f3", "s3"]]
    assert plan[0]["end"] == 250
    assert plan[1]["reason"] == "смена слайда"


def test_long_slide_splits_with_active_frame_and_real_reason():
    sources = [source("f1", 0, "One slide", "slide.jpg"),
               source("s1", 5, "first"), source("s2", 100, "continued")]
    groups, plan = slide_groups(sources, 0, 140, {}, max_seconds=90)
    assert [[s.id for s in group] for group in groups] == [["f1", "s1"], ["f1", "s2"]]
    assert plan[1]["start"] == 100
    assert plan[1]["reason"] == "предел длительности"


def test_text_limit_splits_without_losing_speech():
    sources = [source("s1", 0, "a" * 200), source("s2", 10, "b" * 200)]
    groups, plan = slide_groups(sources, 0, 30, {}, max_chars=400)
    assert [[s.id for s in group] for group in groups] == [["s1"], ["s2"]]
    assert plan[1]["reason"] == "предел текста"


def test_without_ocr_substantial_visual_change_is_boundary():
    sources = [source("f1", 0, "", "one.jpg"), source("s1", 1, "first"),
               source("f2", 50, "", "two.jpg"), source("s2", 51, "second")]
    groups, plan = slide_groups(sources, 0, 100, {"f2": 0.7})
    assert len(groups) == 2
    assert plan[1]["start"] == 50


def short_blocks(count=7):
    groups = [[source(f"s{i}", i * 60, f"speech {i}")] for i in range(count)]
    plan = [{"block": i + 1, "slide": i + 1, "start": i * 60, "end": (i + 1) * 60,
             "reason": "смена слайда", "source_ids": [f"s{i}"]} for i in range(count)]
    return groups, plan


def test_merge_three_minutes_keeps_boundaries_and_absorbs_short_tail():
    groups, plan = short_blocks()
    packed, result = merge_short_groups(groups, plan)
    assert [(b["start"], b["end"]) for b in result] == [(0, 180), (180, 420)]
    assert [s.id for g in packed for s in g] == [f"s{i}" for i in range(7)]
    assert [s["start"] for s in result[0]["segments"]] == [0, 60, 120]


def test_merge_preserves_completed_prefix_and_obeys_size_guards():
    groups, plan = short_blocks()
    packed, result = merge_short_groups(groups, plan, preserve=2)
    assert packed[:2] == groups[:2]
    assert result[:2] == plan[:2]
    assert [(b["start"], b["end"]) for b in result[2:]] == [(120, 420)]
    packed, result = merge_short_groups(groups, plan, max_chars=300)
    assert all(sum(len(s.text) + 128 for s in g) <= 300 for g in packed)
    assert all(b["end"] - b["start"] <= 600 for b in result)
    assert [s.id for g in packed for s in g] == [f"s{i}" for i in range(7)]


def test_merge_deduplicates_carried_frames():
    groups, plan = short_blocks(3)
    frame = source("f1", 0, "same slide", "slide.jpg")
    for group in groups:
        group.insert(0, frame)
    packed, _ = merge_short_groups(groups, plan)
    assert [s.id for s in packed[0]].count("f1") == 1


def test_merge_does_not_exceed_duration_guard_to_absorb_tail():
    groups, plan = short_blocks()
    _, result = merge_short_groups(groups, plan, max_seconds=180)
    assert [(b["start"], b["end"]) for b in result] == [(0, 180), (180, 360), (360, 420)]
