"""Ollama HTTP chat pattern adapted from reels-analyzer/reviewer.py."""

import json
import time
from importlib.resources import files

import requests
from pydantic import BaseModel, Field

from .models import Notes, Source
from .progress import ProgressLog, update_status
from .request_log import RequestJournal

PROMPT = files("video_descriptor").joinpath("prompts/lecture_notes_ru.txt").read_text(
    encoding="utf-8"
)
FILTER_PROMPT = files("video_descriptor").joinpath("prompts/filter_notes_ru.txt").read_text(
    encoding="utf-8"
)
ROUTE_PROMPT = files("video_descriptor").joinpath("prompts/route_vision_ru.txt").read_text(
    encoding="utf-8"
)
QUIZ_PROMPT = files("video_descriptor").joinpath("prompts/quiz_explanation_ru.txt").read_text(
    encoding="utf-8"
)
CONTEXT_PROMPT = files("video_descriptor").joinpath("prompts/context_ru.txt").read_text(encoding="utf-8")


class QuizExplanation(BaseModel):
    question: str
    explanation: str
    source_ids: list[str]


class QuizExplanations(BaseModel):
    explanations: list[QuizExplanation]


class VisionPlan(BaseModel):
    frame_ids: list[str]
    reason: str


class Selection(BaseModel):
    keep: list[int] = Field(description="Indexes of educational notes to retain")


def group_sources(sources: list[Source], start: float, chunk_seconds: float):
    groups = {}
    for source in sorted(sources, key=lambda item: (item.start, item.id)):
        if source.text.strip() or source.image:
            key = int((source.start - start) // chunk_seconds)
            groups.setdefault(key, []).append(source)
    return list(groups.values())


def chat_json(prompt, evidence, schema, model, base_url, log=None, context=16384,
              images=None, metrics=None, task="analysis", output_limit=4096) -> str:
    for attempt in range(3):
        try:
            return _chat_json_once(prompt, evidence, schema, model, base_url, log,
                                   context, images, metrics, task, output_limit)
        except (requests.RequestException, RuntimeError) as exc:
            transient = isinstance(exc, requests.RequestException) or any(
                marker in str(exc) for marker in ("Ollama HTTP 500", "Ollama HTTP 502",
                                                  "Ollama HTTP 503", "поток ответа оборвался"))
            if not transient or attempt == 2:
                raise
            if log:
                log(f"Ollama: сбой соединения/процесса модели; повтор {attempt + 1}/2. "
                    "Выгружаем модель перед повтором этого запроса")
            try:
                response = requests.post(base_url.rstrip("/") + "/api/generate",
                                         json={"model": model, "keep_alive": 0}, timeout=(10, 30))
                response.raise_for_status()
                response.close()
            except requests.RequestException as reset_error:
                if log:
                    log(f"Ollama: выгрузка не удалась: {reset_error}; всё равно повторяем запрос")
            time.sleep(2)


def _chat_json_once(prompt, evidence, schema, model, base_url, log=None, context=16384,
              images=None, metrics=None, task="analysis", output_limit=4096) -> str:
    started = time.monotonic()
    original_prompt, original_evidence = prompt, evidence
    if isinstance(log, ProgressLog) and log.lecture_context is not None:
        evidence = {"lecture_context": log.lecture_context.snapshot(), "current_material": evidence}
        prompt = prompt + "\n\n" + CONTEXT_PROMPT
    message = {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)}
    if images:
        message["images"] = images
    payload = {
        "model": model, "stream": True,
        "think": log.request_thinking() if isinstance(log, ProgressLog) else False,
        "format": schema,
        "options": {"temperature": 0,
                    "num_ctx": max(context, output_limit + 4096, 16384 if task != "translate" else 0),
                    "num_predict": output_limit},
        "messages": [
            {"role": "system", "content": prompt},
            message,
        ],
    }
    if isinstance(log, ProgressLog):
        log.begin_request(task, model, len(prompt) + len(message["content"]),
                          len(json.dumps(payload).encode("utf-8")), len(images or []), output_limit)
        log.update(request_thinking=payload["think"])
    journal = None
    if isinstance(log, ProgressLog) and log.journal_dir is not None:
        journal = RequestJournal(log.journal_dir, base_url.rstrip("/") + "/api/chat",
                                 payload, log.snapshot(), task)
        update_status(log, request_log=str(journal.folder))
        log(f"Журнал запроса: {journal.folder}")
    if log:
        log("Ollama: отправка запроса; ожидаем ответ")
    try:
        response = requests.post(base_url.rstrip("/") + "/api/chat", json=payload,
                                 timeout=(10, 600), stream=True)
    except requests.RequestException as exc:
        if journal:
            journal.finish("connection_error", str(exc))
        update_status(log, request_started=None, request_seconds=time.monotonic() - started,
                      request_state="ошибка соединения")
        raise
    parts = []
    characters = 0
    thinking_characters = 0
    last_update = time.monotonic()
    completed = False
    limited = False
    error = None
    try:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(f"Ollama HTTP {response.status_code}: {response.text[:1500]}") from exc
        for line in response.iter_lines():
            if not line:
                continue
            if journal:
                journal.raw(line)
            event = json.loads(line)
            if journal:
                journal.event(event)
            if event.get("error"):
                raise RuntimeError(f"Ollama: {event['error']}")
            content = event.get("message", {}).get("content", "")
            parts.append(content)
            characters += len(content)
            thinking_characters += len(event.get("message", {}).get("thinking", ""))
            update_status(log, received=characters, thinking=thinking_characters,
                          request_state="получаем ответ" if characters else "ожидаем текст ответа")
            if log and time.monotonic() - last_update >= 5:
                log(f"Ollama: получено {characters} символов ответа")
                last_update = time.monotonic()
            if event.get("done"):
                completed = True
                if metrics is not None:
                    metrics.append({"task": task, "seconds": round(time.monotonic() - started, 2),
                                    "images": len(images or []),
                                    "input_tokens": event.get("prompt_eval_count"),
                                    "output_tokens": event.get("eval_count")})
                limited = event.get("done_reason") == "length"
                update_status(log, input_tokens=event.get("prompt_eval_count"),
                              output_tokens=event.get("eval_count"))
                break
    except BaseException as exc:
        error = str(exc)
        raise
    finally:
        response.close()
        if journal:
            journal.finish("error" if error else "length" if limited else
                           "complete" if completed else "interrupted", error)
        update_status(log, request_started=None, request_seconds=time.monotonic() - started,
                      request_state=("лимит ответа" if limited else "готово")
                      if completed else "ответ прерван")
    if log:
        log("Ollama: запрос завершён" if completed else "Ollama: запрос прерван")
    if not completed:
        raise RuntimeError("Ollama: поток ответа оборвался до завершения")
    if limited:
        if output_limit < 8192:
            if log:
                log(f"Ollama ({task}): достигнут лимит {output_limit} токенов; "
                    "повтор только этого запроса с лимитом 8192")
            return _chat_json_once(original_prompt, original_evidence, schema, model, base_url, log,
                             context=context, images=images, metrics=metrics,
                             task=task, output_limit=8192)
        raise RuntimeError(f"Ollama ({task}): ответ достиг лимита {output_limit} токенов "
                           "даже после повтора; уменьшите --chunk-seconds. "
                           "Готовые блоки сохранены")
    return "".join(parts)


def plan_vision(sources, changes, model, base_url, max_frames, log=None, metrics=None) -> VisionPlan:
    frame_ids = [source.id for source in sources if source.image]
    if not frame_ids:
        return VisionPlan(frame_ids=[], reason="Нет кадров в блоке")
    schema = VisionPlan.model_json_schema()
    schema["properties"]["frame_ids"]["items"]["enum"] = frame_ids
    schema["properties"]["frame_ids"]["maxItems"] = max_frames
    evidence = [{**source.model_dump(exclude={"image"}),
                 "change_fraction": changes.get(source.id)} for source in sources]
    plan = VisionPlan.model_validate_json(chat_json(
        ROUTE_PROMPT, evidence, schema, model, base_url, log, context=16384,
        metrics=metrics, task="route",
    ))
    if set(plan.frame_ids) - set(frame_ids) or len(plan.frame_ids) > max_frames:
        raise ValueError("Модель запросила неизвестные кадры или превысила лимит")
    plan.frame_ids = list(dict.fromkeys(plan.frame_ids))
    return plan


def summarize(sources: list[Source], model: str, base_url: str, log=None,
              images=None, image_sources=None, metrics=None, slide_segments=None) -> Notes:
    selected_ids = {item["id"] for item in image_sources or []}
    evidence = {"sources": [
        {**source.model_dump(exclude={"image"}),
         "text": "" if source.id in selected_ids else source.text} for source in sources
    ],
                "image_sources": image_sources or []}
    if slide_segments:
        evidence["slide_segments"] = slide_segments
        evidence["grouping_note"] = ("В запрос объединены несколько соседних фрагментов. "
                                     "Выделяй отдельные разделы при смене темы; границы слайдов указаны в slide_segments.")
    schema = Notes.model_json_schema()
    for name in ("Note", "VideoSection"):
        schema["$defs"][name]["properties"]["source_ids"]["items"]["enum"] = [
            source.id for source in sources
        ]
    result = Notes.model_validate_json(chat_json(
        PROMPT, evidence, schema, model, base_url, log, images=images,
        metrics=metrics, task="summarize",
    ))
    allowed = {source.id for source in sources}
    for note in [*result.notes, *result.sections]:
        unknown = set(note.source_ids) - allowed
        if unknown:
            raise ValueError(f"Ollama вернула неизвестные источники: {sorted(unknown)}")
    return result


def explain_quizzes(notes: Notes, sources: list[Source], model: str, base_url: str,
                    log=None, metrics=None) -> Notes:
    """Fill omitted quiz explanations from speech without solving or changing answers."""
    missing = {section.quiz.question for section in notes.sections
               if section.quiz and not section.quiz.explanation}
    speech = [source for source in sources if not source.image and source.text.strip()]
    if not missing or not speech:
        return notes
    quizzes = {section.quiz.question: section.quiz.model_dump() for section in notes.sections
               if section.quiz and section.quiz.question in missing}
    schema = QuizExplanations.model_json_schema()
    schema["$defs"]["QuizExplanation"]["properties"]["question"]["enum"] = list(quizzes)
    schema["$defs"]["QuizExplanation"]["properties"]["source_ids"]["items"]["enum"] = [
        source.id for source in speech
    ]
    response = QuizExplanations.model_validate_json(chat_json(
        QUIZ_PROMPT, {"quizzes": list(quizzes.values()),
                      "speech": [source.model_dump(exclude={"image"}) for source in speech]},
        schema, model, base_url, log, context=8192, metrics=metrics, task="quiz_explanation",
    ))
    allowed = {source.id for source in speech}
    if (len(response.explanations) != len(quizzes)
            or {item.question for item in response.explanations} != quizzes.keys()):
        raise ValueError("Модель должна вернуть объяснение для каждого известного вопроса")
    result = notes.model_copy(deep=True)
    for item in response.explanations:
        if set(item.source_ids) - allowed or (item.explanation and not item.source_ids):
            raise ValueError("Объяснение квиза должно подтверждаться существующей речью")
        for section in result.sections:
            if section.quiz and section.quiz.question == item.question:
                section.quiz.explanation = item.explanation
                section.source_ids = list(dict.fromkeys(section.source_ids + item.source_ids))
    return result


def filter_notes(notes: Notes, model: str, base_url: str, log=None, metrics=None) -> Notes:
    if not notes.notes:
        return notes
    evidence = [{"index": index, **note.model_dump(exclude={"source_ids"})}
                for index, note in enumerate(notes.notes)]
    schema = Selection.model_json_schema()
    schema["properties"]["keep"]["items"]["enum"] = list(range(len(notes.notes)))
    selection = Selection.model_validate_json(chat_json(
        FILTER_PROMPT, evidence, schema, model, base_url, log, context=8192,
        metrics=metrics, task="filter",
    ))
    if any(index < 0 or index >= len(notes.notes) for index in selection.keep):
        raise ValueError("Фильтр вернул неизвестный индекс пункта")
    selected = set(selection.keep)
    result = Notes(
        notes=[note for index, note in enumerate(notes.notes) if index in selected],
        sections=notes.sections,
    )
    if log:
        log(f"Фильтрация: оставлено {len(result.notes)}/{len(notes.notes)} учебных пунктов")
    return result
