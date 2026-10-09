"""Group lecture evidence around observed slide changes, with request size guards."""

import re
from bisect import bisect_right
from difflib import SequenceMatcher

from .models import Source


def words(text):
    return re.findall(r"\w+", text.casefold())


def merge_short_groups(groups, plan, min_seconds=180, max_seconds=600, max_chars=18000,
                       preserve=0):
    """Pack short slide groups; retain source IDs, boundaries and a completed prefix."""
    if min_seconds <= 0:
        return groups, plan
    output = [(list(group), [dict(block)]) for group, block in zip(groups[:preserve], plan[:preserve])]
    pending, segments = [], []

    def combine(left, right):
        items = {source.id: source for source in [*left, *right]}
        return sorted(items.values(), key=lambda source: (source.start, source.id))

    def fits(items, parts):
        return (parts[-1]["end"] - parts[0]["start"] <= max_seconds
                and sum(len(source.text) + 128 for source in items) <= max_chars)

    for group, block in zip(groups[preserve:], plan[preserve:]):
        joined = combine(pending, group)
        if pending and not fits(joined, [*segments, block]):
            output.append((pending, segments))
            pending, segments = [], []
            joined = list(group)
        pending, segments = joined, [*segments, dict(block)]
        if segments[-1]["end"] - segments[0]["start"] >= min_seconds:
            output.append((pending, segments))
            pending, segments = [], []
    if pending:
        if len(output) > preserve and fits(combine(output[-1][0], pending), [*output[-1][1], *segments]):
            previous, parts = output.pop()
            output.append((combine(previous, pending), [*parts, *segments]))
        else:
            output.append((pending, segments))
    packed_groups, packed_plan = [], []
    for group, parts in output:
        block = dict(parts[0])
        block.update(block=len(packed_groups) + 1, end=parts[-1]["end"], source_ids=[s.id for s in group])
        if len(parts) > 1:
            block.update(reason="склейка коротких блоков", segments=[
                {key: part[key] for key in ("slide", "start", "end", "reason")} for part in parts])
        packed_groups.append(group)
        packed_plan.append(block)
    return packed_groups, packed_plan


def slide_groups(sources: list[Source], start: float, end: float, changes: dict,
                 max_seconds=600, max_chars=18000, similarity=0.55):
    frames = sorted((s for s in sources if s.image), key=lambda s: (s.start, s.id))
    boundaries = [start]
    previous = None
    for frame in frames:
        current = words(frame.text)
        if previous is not None:
            old = words(previous.text)
            # Highlighting and duplicate control frames should stay with their slide.
            changed = (SequenceMatcher(None, old, current, autojunk=False).ratio() < similarity
                       if len(old) >= 5 and len(current) >= 5
                       else changes.get(frame.id, 0) >= 0.4)
            if changed and start < frame.start < end:
                boundaries.append(frame.start)
        previous = frame
    boundaries = sorted(set(boundaries))
    buckets = [[] for _ in boundaries]
    for source in sorted(sources, key=lambda s: (s.start, s.id)):
        if start <= source.start < end and (source.text.strip() or source.image):
            buckets[bisect_right(boundaries, source.start) - 1].append(source)
    groups, plan = [], []
    def finish(stop, group, segment_start, reason, index):
        # A long slide may require multiple requests: include its active screenshot.
        active = next((f for f in reversed(frames) if f.start <= segment_start), None)
        items = list(group)
        if active and active.id not in {s.id for s in items}:
            items.insert(0, active)
        groups.append(items)
        plan.append({"block": len(groups), "slide": index + 1,
                     "start": segment_start, "end": stop, "reason": reason,
                     "source_ids": [s.id for s in items]})

    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        segment_end = boundaries[index + 1] if index + 1 < len(boundaries) else end
        segment_start = boundaries[index]
        group, chars = [], 0
        reason = "начало" if index == 0 else "смена слайда"

        for source in bucket:
            cost = len(source.text) + 128
            too_long = source.start - segment_start >= max_seconds
            too_large = chars + cost > max_chars
            if group and (too_long or too_large):
                finish(source.start, group, segment_start, reason, index)
                segment_start = source.start
                group, chars = [], 0
                reason = "предел длительности" if too_long else "предел текста"
            group.append(source)
            chars += cost
        if group:
            finish(segment_end, group, segment_start, reason, index)
    return groups, plan
