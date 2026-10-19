"""Lecture display titles and the local report library."""

import html
import json
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote

LOCK = threading.Lock()


def lecture_info(folder):
    root = folder if (folder / "manifest.json").is_file() else folder.parent
    manifest = json.loads((root / "manifest.json").read_text())
    video = manifest["video"]
    metadata = root.parent / "lecture-titles.json"
    titles = json.loads(metadata.read_text()) if metadata.exists() else {}
    title = titles.get(video, "")
    filename = Path(video).name
    return {"title": title, "filename": filename,
            "display": f"{title} [{filename}]" if title else filename}


def save_title(folder, title):
    if not isinstance(title, str):
        raise TypeError("Название должно быть текстом")
    title = " ".join(title.split())
    if len(title) > 200:
        raise ValueError("Название — до 200 символов")
    root = folder if (folder / "manifest.json").is_file() else folder.parent
    video = json.loads((root / "manifest.json").read_text())["video"]
    path = root.parent / "lecture-titles.json"
    with LOCK:
        titles = json.loads(path.read_text()) if path.exists() else {}
        titles[video] = title
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root.parent,
                                         prefix=".lecture-titles-", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                json.dump(titles, stream, ensure_ascii=False, indent=2)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return lecture_info(folder)


def library_page(output):
    lectures = {}
    if output.is_dir():
        for folder in output.iterdir():
            manifest = folder / "manifest.json"
            if not manifest.is_file():
                continue
            try:
                data = json.loads(manifest.read_text())
                full = data.get("start", 0) == 0 and data.get("duration") is None
                score = (full, (folder / "report.html").is_file(), manifest.stat().st_mtime_ns)
                previous = lectures.get(data["video"])
                if previous is None or score > previous[0]:
                    lectures[data["video"]] = (score, folder)
            except (ValueError, KeyError, OSError):
                continue
    cards = []
    for score, folder in sorted(lectures.values(), key=lambda item: item[1].name):
        info = lecture_info(folder)
        ready = ((folder / "report.html").is_file()
                 and (not (folder / "speech.json").is_file() or (folder / "notes.json").is_file()))
        url = "/create?folder=" + quote(folder.name)
        status = "Конспект готов" if ready else "Конспект ещё не создан"
        if (ready and (folder / "analysis-errors.json").exists()
                and json.loads((folder / "analysis-errors.json").read_text())):
            status = "Конспект с пропущенными фрагментами"
        if not score[0]:
            status += " · фрагмент записи"
        report_link = (f' · <a href="{url}&amp;stage=notes">Читать конспект →</a>'
                       if ready else "")
        cards.append(f'<article><a href="{url}">{html.escape(info["display"])}</a>'
                     f'<p>{status}</p><a href="{url}">Открыть запись →</a>'
                     f'{report_link}</article>')
    return ('<!doctype html><html lang="ru"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Записи · Video Descriptor</title>'
            '<link rel="stylesheet" href="/studio-assets/create.css">'
            '<a class="vd-skip" href="#records">К записям</a>'
            '<nav class="vd-global-nav" aria-label="Основная навигация">'
            '<a href="/output/" aria-current="page">Записи</a>'
            '<a href="/#settings">Настройки AI</a><a href="/#diagnostics">Диагностика</a></nav>'
            '<main id="records" tabindex="-1"><div class="library-heading"><h1>Записи</h1>'
            '<a class="vd-button vd-button--primary" href="/">Новая запись</a></div>'
            '<p>Откройте запись для просмотра расшифровки, перевода и конспекта.</p>'
            + ("".join(cards) or '<p>Готовых материалов пока нет.</p>') + '</main></html>')
