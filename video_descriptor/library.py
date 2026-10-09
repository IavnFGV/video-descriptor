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
        ready = (folder / "report.html").is_file()
        url = "/output/" + quote(folder.name) + ("/report.html" if ready else "/")
        status = "Отчёт готов" if ready else "Отчёт ещё не создан"
        if (ready and (folder / "analysis-errors.json").exists()
                and json.loads((folder / "analysis-errors.json").read_text())):
            status = "Отчёт с пропущенными фрагментами"
        if not score[0]:
            status += " · фрагмент видео"
        cards.append(f'<article><a href="{url}">{html.escape(info["display"])}</a>'
                     f'<p>{status}</p><a href="/create?folder={quote(folder.name)}">Ход обработки →</a></article>')
    return ('<!doctype html><html lang="ru"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Лекции</title><style>body{font:16px/1.6 system-ui;max-width:1000px;'
            'margin:32px auto;padding:0 20px;background:#f7f8fa;color:#202b3b}'
            'article{background:white;border:1px solid #e2e7ef;border-radius:12px;'
            'padding:20px;margin:16px 0}a{color:#1557aa;overflow-wrap:anywhere}'
            'article>a{font-size:20px;font-weight:600}p{color:#596579;margin-bottom:0}</style>'
            '<h1>Лекции</h1><p><a href="/create">＋ Создать конспект</a></p>'
            '<p>Откройте отчёт, чтобы читать конспект и изменить название лекции.</p>'
            + ("".join(cards) or '<p>Готовых материалов пока нет.</p>') + '</html>')
