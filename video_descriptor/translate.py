"""Translate cached speech and refresh reports without reanalyzing the lecture."""

import argparse
import hashlib
import json
import logging
import os
import re
from importlib.resources import files
from pathlib import Path

import requests

from .chapters import build_chapters
from .gemini import GeminiServiceError
from .jobs import read_json
from .models import Chapter, Notes, Source
from .notes import chat_json, group_sources
from .progress import ProgressLog, update_status
from .report import render
from .translation_settings import load as translation_settings

PROMPT = files("video_descriptor").joinpath("prompts/translate_markers_ru.txt").read_text(
    encoding="utf-8")
LEGACY_PROMPT = files("video_descriptor").joinpath("prompts/translate_ru.txt").read_text(
    encoding="utf-8")


def translate_batch(sources, model, base_url, log=None):
    markers = [f"[[s{i:04d}]]" for i in range(1, len(sources) + 1)]
    text = "\n\n".join(f"{marker}\n{source.text}"
                         for marker, source in zip(markers, sources))
    settings = getattr(log, "translation_settings", None)
    if settings and settings["provider"] == "gemini":
        from .gemini import translate
        result = translate(PROMPT, text, settings, log)
    else:
        result = chat_json(PROMPT, text, None, model, base_url, log,
                           context=8192, task="translate")
    found = re.findall(r"\[\[s\d+\]\]", result)
    parts = re.split(r"\[\[s\d+\]\]", result)
    if found != markers or parts[0].strip() or not parts[1].strip():
        raise ValueError("Перевод должен сохранить каждую исходную метку ровно один раз "
                         "и в исходном порядке; первый перевод не должен быть пустым")
    return {source.id: part.strip() for source, part in zip(sources, parts[1:])}


def translate_resilient(sources, model, base_url, log=None):
    try:
        return translate_batch(sources, model, base_url, log)
    except (ValueError, RuntimeError) as exc:
        if len(sources) <= 1:
            raise
        if log:
            log(f"Перевод: блок не прошёл проверку ({exc}); делим {len(sources)} реплик пополам")
        middle = len(sources) // 2
        return {**translate_resilient(sources[:middle], model, base_url, log),
                **translate_resilient(sources[middle:], model, base_url, log)}


def refresh_reports(folder: Path, translations=None):
    manifest = json.loads((folder / "manifest.json").read_text())
    video = Path(manifest["video"])
    sources = [Source.model_validate(item) for item in
               json.loads((folder / 'transcript.json').read_text()) + read_json(folder / 'frames.json', [])]
    if translations is None:
        path = folder / "translations.json"
        translations = json.loads(path.read_text()) if path.exists() else {}
    for target in [folder, folder / "off", folder / "auto"]:
        if not (target / "notes.json").exists():
            continue
        notes = Notes.model_validate_json((target / "notes.json").read_text())
        chapter_path = target / "chapters.json"
        chapters = ([Chapter.model_validate(item) for item in json.loads(chapter_path.read_text())]
                    if chapter_path.exists() else build_chapters(notes.sections, sources))
        report_sources = sources if target == folder else [source.model_copy(update={
            "image": f"../{source.image}" if source.image else None
        }) for source in sources]
        render(target, video, report_sources, notes.notes, chapters, translations,
               write_markdown=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="Папка с transcript.json и manifest.json")
    parser.add_argument("--model", default=os.getenv("OLLAMA_MODEL", ""))
    parser.add_argument("--base-url", default=os.getenv(
        "OLLAMA_BASE_URL", "http://host.docker.internal:11434"))
    parser.add_argument("--refresh-only", action="store_true",
                        help="Обновить интерфейс из сохранённых данных без запросов модели")
    parser.add_argument("--device", choices=["auto", "cpu"], default="auto",
                        help="auto — выбор устройства Ollama; cpu — принудительно без GPU")
    args = parser.parse_args()
    folder = args.folder.resolve()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
    log = ProgressLog(logging.getLogger(__name__).info, folder.name, folder / "requests")
    log.progress_file = folder / "progress.json"
    log.num_gpu = 0 if args.device == "cpu" else None
    log.update(model=args.model)
    if args.refresh_only:
        refresh_reports(folder)
        log(f"Отчёт обновлён: {folder / 'report.html'}")
        return 0
    if not args.model.strip():
        parser.error("Укажите --model или OLLAMA_MODEL")
    from .__main__ import save, stage
    try:
        speech = [Source.model_validate(item) for item in
                  json.loads((folder / "transcript.json").read_text())]
        groups = group_sources(speech, 0, 90)
        translation_path = folder / "translations.json"
        translations = (json.loads(translation_path.read_text())
                        if translation_path.exists() else {})
        failures = []
        history_path = folder / "translation-error-history.json"
        history = set(json.loads(history_path.read_text()) if history_path.exists() else [])
        with stage("Перевод субтитров", log):
            for index, group in enumerate(groups, 1):
                from .prompt_settings import effective, overrides
                log.prompt_settings = overrides()
                settings = translation_settings()
                log.translation_settings = settings
                active_model = settings["model"] if settings["provider"] == "gemini" else (settings.get("ollama_model") or args.model)
                active_base = "gemini" if settings["provider"] == "gemini" else args.base_url
                log.reset_request()
                log.update(model=active_model, provider=settings["provider"], estimated_usd=None)
                update_status(log, chunk=f"{index}/{len(groups)}",
                              span=f"{min(s.start for s in group):.0f}–"
                                   f"{max(s.end for s in group):.0f} сек",
                              sources=f"речь {len(group)}, кадры 0", task="перевод")
                key = hashlib.sha256(json.dumps(
                    [effective('translate', PROMPT, log), active_model, active_base, [item.model_dump() for item in group]],
                    sort_keys=True,
                ).encode()).hexdigest()[:12]
                target = folder / f"translation-{key}.json"
                legacy_key = hashlib.sha256(json.dumps(
                    [LEGACY_PROMPT, args.model, args.base_url,
                     [item.model_dump() for item in group]], sort_keys=True,
                ).encode()).hexdigest()[:12]
                legacy_target = folder / f"translation-{legacy_key}.json"
                cached = target if target.exists() or 'translate' in log.prompt_settings else legacy_target
                log(f"Перевод: блок {index}/{len(groups)}")
                try:
                    if all(source.id in translations for source in group):
                        batch = {source.id: translations[source.id] for source in group}
                        update_status(log, request_state="из кэша")
                        log("Перевод блока уже сохранён; переиспользуем независимо от модели")
                    elif cached.exists():
                        update_status(log, request_state="из кэша")
                        batch = json.loads(cached.read_text())
                        log("Перевод блока загружен из кэша")
                    else:
                        batch = translate_resilient(group, active_model, active_base, log)
                        save(target, batch)
                    translations.update(batch)
                    save(folder / "translations.json", translations)
                except GeminiServiceError:
                    raise
                except (RuntimeError, ValueError, requests.RequestException) as exc:
                    history.add(index)
                    save(history_path, sorted(history))
                    failures.append({"block": index, "error": str(exc), "status": log.snapshot()})
                    log(f"ПЕРЕВОД БЛОКА {index}/{len(groups)} ПРОПУЩЕН: {exc}; продолжаем")
                save(folder / "translation-errors.json", failures)
        refresh_reports(folder, translations)
        if failures:
            log(f"ПЕРЕВОД С ПРОПУСКАМИ: {len(failures)} блоков; см. translation-errors.json")
            return 1
        log(f"ГОТОВО: {folder / 'report.html'}")
        return 0
    except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 — CLI preserves completed batches.
        log(f"Перевод прерван: {exc}. Завершённые блоки сохранены.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
