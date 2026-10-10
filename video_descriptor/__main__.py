import argparse
import hashlib
import json
import logging
import math
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import requests

from .cache import cache_digest, reuse_speech
from .chapters import build_chapters
from .chunks import merge_short_groups, slide_groups
from .context import LectureContext
from .media import extract_audio, extract_frames, probe, transcribe
from .models import Notes, Source
from .notes import (
    CONTEXT_PROMPT,
    FILTER_PROMPT,
    PROMPT,
    QUIZ_PROMPT,
    ROUTE_PROMPT,
    VisionPlan,
    explain_quizzes,
    filter_notes,
    group_sources,
    plan_vision,
    summarize,
)
from .progress import ProgressLog, update_status
from .report import render
from .vision import check_vision_model, encode_frames, frame_changes


def save(path: Path, value) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def cached_sources(path: Path, produce, log) -> list[Source]:
    if path.exists():
        log(f"Кэш: {path.name}, повторная обработка не нужна")
        return [Source.model_validate(item) for item in json.loads(path.read_text())]
    result = produce()
    save(path, [item.model_dump() for item in result])
    return result


@contextmanager
def stage(name: str, log):
    started = time.monotonic()
    stop = threading.Event()
    if isinstance(log, ProgressLog):
        log.reset_request()
    update_status(log, stage=name, chunk="—", span="—", sources="—")

    def heartbeat():
        while not stop.wait(15):
            log(f"{name}: выполняется, прошло {time.monotonic() - started:.0f} сек")

    log(f"{name}: начало")
    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    completed = False
    try:
        yield
        completed = True
    finally:
        stop.set()
        worker.join()
        status = "готово" if completed else "прерван"
        log(f"{name}: {status}, {time.monotonic() - started:.1f} сек")


def positive(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Нужно конечное число больше нуля")
    return number


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Нужно целое число больше нуля")
    return number


def scene_threshold(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise argparse.ArgumentTypeError("Порог scene должен быть от 0 до 1")
    return number


def main() -> int:
    parser = argparse.ArgumentParser(description="Видео → транскрипция, OCR и русский конспект")
    parser.add_argument("video", type=Path)
    parser.add_argument("--start", type=float, default=0, help="Начало фрагмента, секунды")
    parser.add_argument("--duration", type=positive, help="Длина фрагмента; по умолчанию всё видео")
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--whisper-model", default="base.en")
    parser.add_argument("--language", default=os.getenv("TRANSCRIPT_LANGUAGE", "en"))
    parser.add_argument("--ocr-language", default="eng")
    parser.add_argument("--frame-interval", type=positive, default=15)
    parser.add_argument("--frame-strategy", choices=["scene", "interval"], default="scene")
    parser.add_argument("--scan-interval", type=positive, default=1,
                        help="scene: интервал проверки изменений, секунды")
    parser.add_argument("--scene-threshold", type=scene_threshold, default=0.01)
    parser.add_argument("--max-frame-gap", type=positive, default=60,
                        help="scene: контрольный кадр через этот интервал, секунды")
    parser.add_argument("--chunk-seconds", type=positive, default=180)
    parser.add_argument("--chunk-strategy", choices=["time", "slides"],
                        help="По умолчанию slides для scene, time для interval")
    parser.add_argument("--max-chunk-seconds", type=positive, default=600)
    parser.add_argument("--max-chunk-chars", type=positive_int, default=18000)
    parser.add_argument("--min-chunk-seconds", type=float, default=180,
                        help="Объединять короткие группы слайдов до этой длительности; 0 — выключить")
    parser.add_argument("--preserve-blocks", type=int, default=0,
                        help="Сохранить первые N блоков прежней нарезки, склеивать только остаток")
    parser.add_argument("--slide-similarity", type=scene_threshold, default=0.55)
    parser.add_argument("--without-context", action="store_true", help="Не передавать историю блоков")
    parser.add_argument("--think", action="store_true", help="Включить передаваемые моделью рассуждения (медленнее)")
    parser.add_argument("--reuse-completed-blocks", action="store_true",
                        help="При исправлении пропусков использовать готовые блоки с их исходным контекстом")
    parser.add_argument("--vision", choices=["auto", "off"], default="auto",
                        help="auto: модель запрашивает картинки; off: только OCR и речь")
    parser.add_argument("--vision-frames", type=positive_int, default=4,
                        help="Максимум запрашиваемых картинок в одном блоке")
    parser.add_argument("--image-max-side", type=positive_int, default=960)
    parser.add_argument("--model", default=os.getenv("OLLAMA_MODEL", ""))
    parser.add_argument("--base-url", default=os.getenv(
        "OLLAMA_BASE_URL", "http://host.docker.internal:11434"
    ))
    parser.add_argument("--skip-notes", action="store_true", help="Только транскрипция и OCR")
    parser.add_argument("--audio-only", action="store_true", help="Пропустить кадры и OCR; создать обычный конспект и отчёт")
    parser.add_argument("--speech-result", type=Path, help="Готовый speech.json выбранного обработчика речи")
    args = parser.parse_args()
    args.chunk_strategy = args.chunk_strategy or ("slides" if args.frame_strategy == "scene" else "time")
    if args.audio_only:
        args.vision = "off"
        args.chunk_strategy = "time"
    if not args.video.is_file():
        parser.error(f"Видео не найдено: {args.video}")
    if not math.isfinite(args.start) or args.start < 0:
        parser.error("--start должен быть конечным неотрицательным числом")
    if not args.skip_notes and not args.model.strip():
        parser.error("Укажите установленную Ollama-модель через --model или OLLAMA_MODEL")
    video = args.video.resolve()
    stat = video.stat()
    identity = {
        "video": str(video), "size": stat.st_size, "mtime": stat.st_mtime_ns,
        "start": args.start, "duration": args.duration, "whisper": args.whisper_model,
        "language": args.language, "interval": args.frame_interval, "ocr": args.ocr_language,
        "version": 1,
    }
    frame_settings = {"strategy": args.frame_strategy}
    if args.frame_strategy == "scene":
        frame_settings.update({"scan_interval": args.scan_interval,
                               "threshold": args.scene_threshold, "max_gap": args.max_frame_gap,
                               "version": 1})
        identity["frame_selection"] = frame_settings
    if args.audio_only:
        identity["mode"] = "audio"
    speech_result = None
    if args.speech_result:
        speech_result = json.loads(args.speech_result.read_text(encoding="utf-8"))
        if speech_result.get("status") != "done":
            parser.error("Распознавание речи ещё не завершено")
        from .speech import editable_result
        speech_result = editable_result(args.speech_result.parent, speech_result)
        if (args.speech_result.parent / "manifest.json").is_file():
            previous = json.loads((args.speech_result.parent / "manifest.json").read_text())
            if Path(previous["video"]).resolve() != video:
                parser.error("Результат речи относится к другому файлу")
        identity["engine"] = speech_result["engine"]
    digest = cache_digest(identity)
    folder = args.speech_result.resolve().parent if args.speech_result else args.output.resolve() / f"{video.stem}-{digest}"
    folder.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("video_descriptor")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    for handler in [logging.StreamHandler(), logging.FileHandler(folder / "run.log", encoding="utf-8")]:
        handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s", "%H:%M:%S"))
        logger.addHandler(handler)
    log = ProgressLog(logger.info, video.name, folder / "requests")
    log.progress_file = folder / "progress.json"
    log.thinking_enabled = args.think
    log.update(model=args.model)
    run_started = time.monotonic()
    metrics = []
    prepared_images = 0
    cached_blocks = 0
    analysis_started = None
    try:
        log(f"Результаты и лог: {folder}")
        with stage("[1/5] Проверка видео", log):
            if args.vision == "auto" and not args.skip_notes:
                check_vision_model(args.model, args.base_url)
            info = probe(video)
            duration = float(info["format"]["duration"]) - args.start
            if duration <= 0:
                raise ValueError("Начало фрагмента находится за концом видео")
            duration = min(duration, args.duration or duration)
            if not args.audio_only and not any(item.get("codec_type") == "video" for item in info["streams"]):
                raise ValueError("В файле нет видеодорожки")
            save(folder / "manifest.json", {**identity, "processed_duration": duration})
            log(f"Фрагмент: {args.start:.0f}–{args.start + duration:.0f} сек")
        with stage("[2/5] Аудио и распознавание", log):
            if speech_result is None:
                reuse_speech(folder, identity, log)
            if speech_result is not None:
                speech = [Source(id=row.get("id", f"s{index}"), start=row["start"], end=row["end"], text=row["text"])
                          for index, row in enumerate(speech_result["segments"], 1)]
                save(folder / "transcript.json", [source.model_dump() for source in speech])
                log("Речь из выбранного обработчика; повторное распознавание не требуется")
            elif any(item.get("codec_type") == "audio" for item in info["streams"]):
                audio = folder / "audio.wav"
                if not audio.exists():
                    extract_audio(video, audio, args.start, duration)
                speech = cached_sources(folder / "transcript.json", lambda: transcribe(
                    audio, args.start, duration, args.whisper_model, args.language, log
                ), log)
            else:
                log("Нет звуковой дорожки; конспект будет опираться на OCR")
                speech = []
                save(folder / "transcript.json", [])
        with stage("[3/5] Кадры и OCR", log):
            if args.audio_only:
                frames = []
                save(folder / "frames.json", [])
                log("Анализ изображения пропущен")
            else:
                frames = cached_sources(folder / "frames.json", lambda: extract_frames(
                    video, folder / "frames", args.start, duration, args.frame_interval,
                    args.ocr_language, log,
                    strategy=args.frame_strategy, scan_interval=args.scan_interval,
                    threshold=args.scene_threshold, max_gap=args.max_frame_gap,
                ), log)
        sources = speech + frames
        notes = []
        sections = []
        changes = frame_changes(frames, folder) if args.vision == "auto" or args.chunk_strategy == "slides" else {}
        with stage("[4/5] Русский конспект", log):
            analysis_started = time.monotonic()
            if not args.skip_notes:
                groups = group_sources(sources, args.start, args.chunk_seconds)
                chunk_plan = []
                key_settings = [args.model, args.base_url, args.chunk_seconds, PROMPT, args.vision,
                                ROUTE_PROMPT, args.vision_frames, args.image_max_side]
                if not args.without_context:
                    log.lecture_context = LectureContext()
                    key_settings.append(["lecture-context-v1", CONTEXT_PROMPT])
                if args.chunk_strategy == "slides":
                    groups, chunk_plan = slide_groups(
                        sources, args.start, args.start + duration, changes,
                        args.max_chunk_seconds, args.max_chunk_chars, args.slide_similarity)
                    key_settings.append(["slides-v1", args.max_chunk_seconds,
                                         args.max_chunk_chars, args.slide_similarity, chunk_plan])
                legacy_notes_key = hashlib.sha256(json.dumps(key_settings).encode()).hexdigest()[:10]
                if not math.isfinite(args.min_chunk_seconds) or args.min_chunk_seconds < 0 or args.preserve_blocks < 0:
                    raise ValueError("Минимальная длительность и число сохранённых блоков должны быть неотрицательными")
                if args.preserve_blocks > len(groups):
                    raise ValueError("Число сохранённых блоков превышает число блоков прежней нарезки")
                if args.preserve_blocks and args.chunk_strategy != "slides":
                    raise ValueError("--preserve-blocks применяется только к стратегии slides")
                if args.chunk_strategy == "slides" and args.min_chunk_seconds > 0:
                    old_count = len(groups)
                    groups, chunk_plan = merge_short_groups(
                        groups, chunk_plan, args.min_chunk_seconds, args.max_chunk_seconds,
                        args.max_chunk_chars, args.preserve_blocks)
                    key_settings.append(["merge-short-v1", args.min_chunk_seconds, args.preserve_blocks, chunk_plan])
                    log(f"Склейка до {args.min_chunk_seconds:.0f} сек: {old_count} → {len(groups)} блоков; "
                        f"сохранено без склейки {args.preserve_blocks}")
                notes_key = hashlib.sha256(json.dumps(key_settings).encode()).hexdigest()[:10]
                save(folder / f"chunk-plan-{notes_key}.json", {
                    "strategy": args.chunk_strategy, "blocks": chunk_plan,
                    "count": len(groups), "max_seconds": args.max_chunk_seconds,
                    "max_chars": args.max_chunk_chars, "slide_similarity": args.slide_similarity,
                    "min_seconds": args.min_chunk_seconds, "preserved_blocks": args.preserve_blocks})
                log(f"Группировка {args.chunk_strategy}: {len(groups)} блоков")
                errors_path = folder / f"failures-{notes_key}.json"
                failures = {item["block"]: item for item in
                            json.loads(errors_path.read_text())} if errors_path.exists() else {}
                legacy_errors = folder / f"failures-{legacy_notes_key}.json"
                if args.preserve_blocks and legacy_errors.exists():
                    for item in json.loads(legacy_errors.read_text()):
                        if item["block"] <= args.preserve_blocks:
                            failures.setdefault(item["block"], {**item, "total_blocks": len(groups)})
                save(folder / "analysis-errors.json", list(failures.values()))
                for index, group in enumerate(groups, 1):
                    from .prompt_settings import overrides
                    log.prompt_settings = overrides()
                    history = None
                    cache_notes_key = legacy_notes_key if index <= args.preserve_blocks else notes_key
                    block_key = cache_notes_key
                    if log.lecture_context is not None:
                        history = log.lecture_context.snapshot()
                        digest = hashlib.sha256(json.dumps(history, sort_keys=True).encode()).hexdigest()[:10]
                        block_key = f"{cache_notes_key}-{digest}"
                        if args.reuse_completed_blocks:
                            completed = sorted(folder.glob(f"notes-{cache_notes_key}-*-{index:04d}.json"),
                                               key=lambda p: p.stat().st_mtime_ns, reverse=True)
                            if completed:
                                candidate_key = completed[0].stem.removeprefix("notes-").rsplit("-", 1)[0]
                                original = folder / f"context-input-{candidate_key}-{index:04d}.json"
                                if original.exists():
                                    history = json.loads(original.read_text())
                                    log.lecture_context.restore(history)
                                    block_key = candidate_key
                        save(folder / f"context-input-{block_key}-{index:04d}.json", history)
                    if log.prompt_settings:
                        prompt_digest = hashlib.sha256(json.dumps(log.prompt_settings, sort_keys=True).encode()).hexdigest()[:10]
                        if not block_key.endswith(f"-p{prompt_digest}"):
                            block_key += f"-p{prompt_digest}"
                        if history is not None:
                            save(folder / f"context-input-{block_key}-{index:04d}.json", history)
                    log.reset_request()
                    update_status(log, chunk=f"{index}/{len(groups)}",
                                  span=f"{min(s.start for s in group):.0f}–"
                                       f"{max(s.end for s in group):.0f} сек",
                                  sources=f"речь {sum(not s.image for s in group)}, "
                                          f"кадры {sum(bool(s.image) for s in group)}")
                    if chunk_plan:
                        block = chunk_plan[index - 1]
                        update_status(log, span=f"{block['start']:.0f}–{block['end']:.0f} сек")
                        log(f"Слайд {block['slide']}: граница — {block['reason']}")
                    try:
                        target = folder / f"notes-{block_key}-{index:04d}.json"
                        log(f"Ollama: блок {index}/{len(groups)}, модель {args.model}")
                        if target.exists():
                            update_status(log, task="конспект", request_state="из кэша")
                            cached_blocks += 1
                            result = Notes.model_validate_json(target.read_text())
                            log("Блок конспекта загружен из кэша")
                        else:
                            images, image_sources = [], []
                            if args.vision == "auto":
                                route_target = folder / f"vision-route-{block_key}-{index:04d}.json"
                                log(f"Решение об осмотре картинок: блок {index}/{len(groups)}")
                                if route_target.exists():
                                    update_status(log, task="выбор картинок", request_state="из кэша")
                                    plan = VisionPlan.model_validate_json(route_target.read_text())
                                else:
                                    plan = plan_vision(group, changes, args.model, args.base_url,
                                                       args.vision_frames, log, metrics)
                                    save(route_target, plan.model_dump())
                                log(f"Модель запросила {len(plan.frame_ids)} кадров: {plan.frame_ids}. "
                                    f"Причина: {plan.reason}")
                                images, image_sources = encode_frames(
                                    group, plan.frame_ids, folder, args.image_max_side,
                                )
                                prepared_images += len(images)
                                save(folder / f"vision-inputs-{block_key}-{index:04d}.json", image_sources)
                            result = summarize(group, args.model, args.base_url, log,
                                               images=images, image_sources=image_sources, metrics=metrics,
                                               **({"slide_segments": chunk_plan[index - 1]["segments"]}
                                                  if chunk_plan and chunk_plan[index - 1].get("segments") else {}))
                            save(target, result.model_dump())
                        if any(section.quiz and not section.quiz.explanation
                               for section in result.sections):
                            quiz_key = hashlib.sha256(json.dumps(
                                [args.model, args.base_url, log.prompt_settings.get('quiz_explanation', QUIZ_PROMPT), result.model_dump(), history],
                                sort_keys=True,
                            ).encode()).hexdigest()[:10]
                            quiz_target = folder / f"quiz-explained-{quiz_key}.json"
                            log(f"Объяснение вопросов по речи: блок {index}/{len(groups)}")
                            if quiz_target.exists():
                                log.reset_request()
                                update_status(log, task="объяснение квиза", request_state="из кэша")
                                result = Notes.model_validate_json(quiz_target.read_text())
                            else:
                                result = explain_quizzes(result, group, args.model,
                                                         args.base_url, log, metrics)
                                save(quiz_target, result.model_dump())
                        filter_key = hashlib.sha256(json.dumps(
                            [args.model, args.base_url, log.prompt_settings.get('filter', FILTER_PROMPT), result.model_dump(), args.vision, history],
                            sort_keys=True,
                        ).encode()).hexdigest()[:10]
                        filtered_target = folder / f"filtered-{filter_key}.json"
                        log(f"Фильтрация учебного материала: блок {index}/{len(groups)}")
                        if filtered_target.exists():
                            log.reset_request()
                            update_status(log, task="фильтрация", request_state="из кэша")
                            filtered = Notes.model_validate_json(filtered_target.read_text())
                            log("Отфильтрованный блок загружен из кэша")
                        else:
                            filtered = filter_notes(result, args.model, args.base_url, log, metrics)
                            save(filtered_target, filtered.model_dump())
                        notes.extend(filtered.notes)
                        sections.extend(result.sections)
                        log(f"Разметка видео: найдено {len(result.sections)} разделов в блоке")
                        log(f"Конспект: {index}/{len(groups)} ({index / len(groups) * 100:.0f}%)")
                        save(folder / f"metrics-{args.vision}-partial.json", {"calls": metrics})
                    except (RuntimeError, ValueError, requests.RequestException) as exc:
                        if log.lecture_context is not None:
                            log.lecture_context.failed()
                        failures[index] = {"block": index, "total_blocks": len(groups),
                                           "start": chunk_plan[index - 1]["start"] if chunk_plan else min(s.start for s in group),
                                           "end": chunk_plan[index - 1]["end"] if chunk_plan else max(s.end for s in group),
                                           "source_ids": [s.id for s in group],
                                           "error": str(exc), "status": log.snapshot()}
                        log(f"БЛОК {index}/{len(groups)} ПРОПУЩЕН: {exc}; переходим к следующему")
                    else:
                        if log.lecture_context is not None:
                            log.lecture_context.advance(result)
                        failures.pop(index, None)
                    save(errors_path, list(failures.values()))
                    save(folder / "analysis-errors.json", list(failures.values()))
                    save(folder / "notes-live.json", {"notes": [n.model_dump() for n in notes],
                                                       "sections": [s.model_dump() for s in sections],
                                                       "completed_block": index, "total_blocks": len(groups)})
            else:
                log("Конспект пропущен по --skip-notes")
        analysis_seconds = time.monotonic() - analysis_started
        with stage("[5/5] Сохранение отчёта", log):
            translation_path = folder / "translations.json"
            translations = json.loads(translation_path.read_text()) if translation_path.exists() else {}
            chapters = build_chapters(sections, sources)
            save(folder / "notes.json", Notes(notes=notes, sections=sections).model_dump())
            save(folder / "chapters.json", [chapter.model_dump() for chapter in chapters])
            render(folder, video, sources, notes, chapters, translations)
            if not args.skip_notes:
                report_folder = folder / args.vision
                report_folder.mkdir(exist_ok=True)
                report_sources = [source.model_copy(update={
                    "image": f"../{source.image}" if source.image else None
                }) for source in sources]
                save(report_folder / "analysis-errors.json", list(failures.values()))
                save(report_folder / "notes.json", Notes(notes=notes, sections=sections).model_dump())
                save(report_folder / "chapters.json", [chapter.model_dump() for chapter in chapters])
                render(report_folder, video, report_sources, notes, chapters, translations)
                stats = {"mode": args.vision, "processed_seconds": duration,
                         "model": args.model, "chunk_seconds": args.chunk_seconds,
                         "chunk_strategy": args.chunk_strategy,
                         "frame_interval": args.frame_interval,
                         "frame_selection": frame_settings,
                         "run_seconds": round(time.monotonic() - run_started, 2),
                         "analysis_seconds": round(analysis_seconds, 2),
                         "images_sent": prepared_images, "calls": metrics,
                         "cached_blocks": cached_blocks,
                         "notes": len(notes), "chapters": len(chapters)}
                save(report_folder / "metrics-last.json", stats)
                if metrics or not (report_folder / "metrics.json").exists():
                    save(report_folder / "metrics.json", stats)
                log(f"Замер: анализ {analysis_seconds:.1f} сек, "
                    f"отправлено картинок: {prepared_images}, запросов: {len(metrics)}")
                log(f"Отчёт {args.vision}: {report_folder / 'report.html'}")
        if not args.skip_notes and failures:
            log(f"ОТЧЁТ С ПРОПУСКАМИ: {len(failures)} блоков; ошибки: {errors_path}")
        log(f"ГОТОВО: {folder / 'report.html'}")
        return 0
    except KeyboardInterrupt:
        log("ОСТАНОВЛЕНО. Завершённые этапы сохранены; повторите ту же команду.")
        return 130
    except Exception as exc:  # noqa: BLE001 — CLI boundary preserves completed stages on failure.
        log(f"ОШИБКА: {exc}. Завершённые этапы сохранены; повторите ту же команду.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
