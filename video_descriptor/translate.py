"""Translate cached speech and refresh reports without reanalyzing the lecture."""

import argparse
import hashlib
import json
import logging
import os
from importlib.resources import files
from pathlib import Path

import requests
from pydantic import BaseModel

from .chapters import build_chapters
from .models import Chapter, Notes, Source
from .notes import chat_json, group_sources
from .progress import ProgressLog, update_status
from .report import render

PROMPT = files("video_descriptor").joinpath("prompts/translate_ru.txt").read_text(encoding="utf-8")


class Translation(BaseModel):
    id: str
    text: str


class Translations(BaseModel):
    segments: list[Translation]


def translate_batch(sources, model, base_url, log=None):
    ids = {source.id for source in sources}
    schema = Translations.model_json_schema()
    schema["$defs"]["Translation"]["properties"]["id"]["enum"] = sorted(ids)
    result = Translations.model_validate_json(chat_json(
        PROMPT, [source.model_dump(exclude={"image"}) for source in sources], schema,
        model, base_url, log, context=8192, task="translate",
    ))
    if ({segment.id for segment in result.segments} != ids
            or len(result.segments) != len(ids)
            or any(not segment.text.strip() for segment in result.segments)):
        raise ValueError("Перевод должен содержать каждый исходный ID ровно один раз")
    return {segment.id: segment.text for segment in result.segments}


def refresh_reports(folder: Path, translations=None):
    manifest = json.loads((folder / "manifest.json").read_text())
    video = Path(manifest["video"])
    sources = [Source.model_validate(item) for name in ("transcript.json", "frames.json")
               for item in json.loads((folder / name).read_text())]
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
    args = parser.parse_args()
    folder = args.folder.resolve()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
    log = ProgressLog(logging.getLogger(__name__).info, folder.name, folder / "requests")
    log.progress_file = folder / "progress.json"
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
        translations = {}
        failures = []
        with stage("Перевод субтитров", log):
            for index, group in enumerate(groups, 1):
                log.reset_request()
                update_status(log, chunk=f"{index}/{len(groups)}",
                              span=f"{min(s.start for s in group):.0f}–"
                                   f"{max(s.end for s in group):.0f} сек",
                              sources=f"речь {len(group)}, кадры 0", task="перевод")
                key = hashlib.sha256(json.dumps(
                    [PROMPT, args.model, args.base_url, [item.model_dump() for item in group]],
                    sort_keys=True,
                ).encode()).hexdigest()[:12]
                target = folder / f"translation-{key}.json"
                log(f"Перевод: блок {index}/{len(groups)}")
                try:
                    if target.exists():
                        update_status(log, request_state="из кэша")
                        batch = json.loads(target.read_text())
                        log("Перевод блока загружен из кэша")
                    else:
                        batch = translate_batch(group, args.model, args.base_url, log)
                        save(target, batch)
                    translations.update(batch)
                    save(folder / "translations.json", translations)
                except (RuntimeError, ValueError, requests.RequestException) as exc:
                    failures.append({"block": index, "error": str(exc), "status": log.snapshot()})
                    log(f"ПЕРЕВОД БЛОКА {index}/{len(groups)} ПРОПУЩЕН: {exc}; продолжаем")
                save(folder / "translation-errors.json", failures)
        refresh_reports(folder, translations)
        if failures:
            log(f"ПЕРЕВОД С ПРОПУСКАМИ: {len(failures)} блоков; см. translation-errors.json")
        log(f"ГОТОВО: {folder / 'report.html'}")
        return 0
    except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 — CLI preserves completed batches.
        log(f"Перевод прерван: {exc}. Завершённые блоки сохранены.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
