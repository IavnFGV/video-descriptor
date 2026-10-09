from .models import Chapter, Source, VideoSection


def build_chapters(sections: list[VideoSection], sources: list[Source]) -> list[Chapter]:
    """Resolve model-selected IDs to real source times; merge continuing sections."""
    by_id = {source.id: source for source in sources}
    chapters = []
    for section in sections:
        unknown = set(section.source_ids) - by_id.keys()
        if unknown:
            raise ValueError(f"Раздел ссылается на неизвестные источники: {sorted(unknown)}")
        evidence = [by_id[key] for key in section.source_ids]
        chapters.append(Chapter(
            **section.model_dump(), start=min(source.start for source in evidence),
            end=max(source.end for source in evidence),
        ))
    chapters.sort(key=lambda chapter: (chapter.start, chapter.end))
    merged = []
    for chapter in chapters:
        same_quiz = bool(merged and merged[-1].quiz and chapter.quiz
                         and merged[-1].quiz.question.casefold().split()
                         == chapter.quiz.question.casefold().split())
        same_section = bool(merged and not merged[-1].quiz and not chapter.quiz
                            and merged[-1].kind == chapter.kind
                            and merged[-1].title == chapter.title)
        # A question and its revealed answer can have a voting pause between them.
        if merged and (same_quiz or (same_section and chapter.start <= merged[-1].end)):
            previous = merged[-1]
            previous.end = max(previous.end, chapter.end)
            previous.source_ids = list(dict.fromkeys(previous.source_ids + chapter.source_ids))
            previous.items = list(dict.fromkeys(previous.items + chapter.items))
            if same_quiz:
                old_quiz, new_quiz = previous.quiz, chapter.quiz
                if (old_quiz.correct_option and new_quiz.correct_option
                        and old_quiz.correct_option != new_quiz.correct_option):
                    old_quiz.explanation += (
                        f" Источники расходятся: {old_quiz.correct_option} и "
                        f"{new_quiz.correct_option}. Проверьте кадры и объяснение преподавателя. "
                        + new_quiz.explanation
                    )
                    old_quiz.correct_option = None
                    previous.quiz = old_quiz
                    continue
                if new_quiz.correct_option is not None:
                    previous.quiz = new_quiz
                elif not old_quiz.explanation and new_quiz.explanation:
                    old_quiz.explanation = new_quiz.explanation
            if chapter.visual_evidence and chapter.visual_evidence != previous.visual_evidence:
                previous.visual_evidence += " " + chapter.visual_evidence
        else:
            merged.append(chapter)
    return merged
