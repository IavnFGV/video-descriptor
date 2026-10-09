"""Bounded lecture context reconstructed from completed blocks, including cached ones."""


def compact(text, words=20, chars=240):
    return " ".join(text.split()[:words])[:chars]


class LectureContext:
    def __init__(self):
        self.plan = []
        self.topics = []
        self.previous = ""
        self.recent = []
        self.gap = False

    def snapshot(self):
        return {"lecture_plan": self.plan[:20], "covered_topics": self.topics[-20:],
                "recent_summaries": self.recent[-5:], "previous_block_summary": self.previous,
                "previous_block_failed": self.gap}

    def restore(self, value):
        self.plan = list(value.get("lecture_plan", []))
        self.topics = list(value.get("covered_topics", []))
        self.previous = value.get("previous_block_summary", "")
        self.recent = list(value.get("recent_summaries", []))
        self.gap = value.get("previous_block_failed", False)

    def advance(self, result):
        for topic in result.lecture_plan:
            topic = compact(topic, 16, 120)
            if topic and topic not in self.plan:
                self.plan.append(topic)
        self.plan = self.plan[:20]
        for section in result.sections:
            title = compact(section.title, 12, 100)
            if title and title not in self.topics:
                self.topics.append(title)
        self.topics = self.topics[-20:]
        summary = result.context_summary or "; ".join(
            [note.title for note in result.notes] or [s.title for s in result.sections])
        self.previous = compact(summary)
        if self.previous:
            self.recent.append(self.previous)
            self.recent = self.recent[-5:]
        self.gap = False

    def failed(self):
        self.previous = ""
        self.gap = True
