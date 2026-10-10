"""Serve reports and support byte ranges for browser video seeking."""

import argparse
import json
import os
import re
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from . import translation_settings
from .editor import EditConflict, load_document, save_document
from .gemini import GeminiServiceError
from .gemini import models as gemini_models
from .jobs import enqueue, find_result, jobs_dir, read_json, start_worker, write_json
from .library import lecture_info, library_page, save_title
from .live import runs, snapshot


class RangeRequestHandler(SimpleHTTPRequestHandler):
    byte_range = None

    def editor_folder(self):
        path = urlsplit(self.path).path
        if not path.endswith(("/editor.json", "/title.json")):
            raise ValueError("Неизвестный адрес редактора")
        folder = Path(self.translate_path(path)).parent.resolve()
        folder.relative_to((Path(self.directory) / "output").resolve())
        if path.endswith('/title.json'):
            if not ((folder / 'manifest.json').is_file() or (folder.parent / 'manifest.json').is_file()):
                raise ValueError('Запись не найдена')
        elif not (folder / "report.html").is_file():
            raise ValueError("Отчёт не найден")
        return folder

    def json_response(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        root = Path(self.directory).resolve()
        if any(part.startswith(".") for part in Path(unquote(path)).parts if part not in ("/", ".")):
            return self.send_error(403)
        params = parse_qs(urlsplit(self.path).query)
        if path in ("/speech", "/studio-assets/speech.html"):
            query = urlsplit(self.path).query
            self.send_response(302)
            self.send_header("Location", "/create" + ("?" + query if query else ""))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/create" or path.startswith("/studio-assets/"):
            name = "create.html" if path == "/create" else path.removeprefix("/studio-assets/")
            if name not in ("create.html", "create.js", "create.css", "studio.js", "report-embed.js", "editor.js", "speech-edit.js", 'construction.js'):
                return self.send_error(404)
            body = files("video_descriptor").joinpath("assets", name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", {"html": "text/html", "js": "text/javascript", "css": "text/css"}[name.split('.')[-1]] + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/api/"):
            try:
                if path == '/api/construction-settings':
                    from .construction import PROMPTS, load_settings
                    return self.json_response(200, {'settings': load_settings(root), 'prompts': PROMPTS})
                if path == '/api/construction-models':
                    from .construction import available_models
                    return self.json_response(200, available_models(root, params.get('provider', ['ollama'])[0]))
                if path == "/api/prompts":
                    from .prompt_settings import public
                    return self.json_response(200, public(root))
                if path in ("/api/subtitles", "/api/transcript-text"):
                    from .speech import editable_result, subtitle_result
                    from .subtitles import webvtt
                    name = params.get("folder", [""])[0]
                    if not name or Path(name).name != name:
                        raise ValueError("Неизвестная папка")
                    folder = (root / "output" / name).resolve()
                    folder.relative_to(root / "output")
                    result = editable_result(folder, subtitle_result(folder))
                    language = params.get("language", ["original"])[0]
                    if language not in ("original", "ru"):
                        raise ValueError("Неизвестный язык")
                    if path == "/api/transcript-text":
                        from .subtitles import plain_transcript
                        body = plain_transcript(result).encode()
                    else:
                        body = webvtt(result, language).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8" if path == "/api/transcript-text" else "text/vtt; charset=utf-8")
                    self.send_header("Content-Disposition", 'attachment; filename="transcript.txt"' if path == "/api/transcript-text" else f'attachment; filename="{language}.vtt"')
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path in ("/api/speech", "/api/speech-inventory"):
                    from .speech import inventory, state
                    return self.json_response(200, inventory(root) if path.endswith("inventory") else state(root, params))
                if path == "/api/translation-settings":
                    return self.json_response(200, translation_settings.public(translation_settings.load(root)))
                if path == "/api/gemini-models":
                    return self.json_response(200, gemini_models(translation_settings.load(root)["api_key"]))
                if path == "/api/runs":
                    return self.json_response(200, runs(root))
                if path == "/api/jobs":
                    return self.json_response(200, [job for p in jobs_dir(root).glob("*/job.json") if (job := read_json(p, {})).get("status") != "deleted"])
                if path == "/api/job":
                    id = params.get("id", [""])[0]
                    if not re.fullmatch(r"[0-9a-f]{32}", id):
                        raise ValueError("Неизвестное задание")
                    job = read_json(jobs_dir(root) / id / "job.json")
                    if job is None:
                        raise ValueError("Задание не найдено")
                    folder = (root / "output" / job["folder"] if job.get("folder") else
                              None if job.get("mode") == "audio" else find_result(root, job["video"]))
                    return self.json_response(200, {"job": job, "progress": snapshot(root, folder) if folder else None})
                if path in ("/api/progress", "/api/request"):
                    name = params.get("folder", [""])[0]
                    if not name or Path(name).name != name:
                        raise ValueError("Неизвестная папка")
                    folder = (root / "output" / name).resolve()
                    folder.relative_to(root / "output")
                    if path == "/api/request":
                        request = params.get("request", [""])[0]
                        if not request or Path(request).name != request:
                            raise ValueError("Неизвестный запрос")
                        file = (folder / "requests" / request / "request.json").resolve()
                        file.relative_to(folder / "requests")
                        value = read_json(file)
                        if value is None:
                            raise ValueError("Запрос не найден")
                        return self.json_response(200, value)
                    return self.json_response(200, snapshot(root, folder))
                raise ValueError("Неизвестный адрес")
            except (ValueError, OSError, KeyError, GeminiServiceError) as exc:
                return self.json_response(404, {"error": str(exc)})
        if path in ("/", "/output/", "/output"):
            body = library_page(Path(self.directory) / "output").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if not path.endswith(("/editor.json", "/title.json")):
            if path.endswith("/report.html"):
                report = Path(self.translate_path(path))
                if (report.parent / "speech.json").is_file() and not (report.parent / "notes.json").is_file():
                    self.send_response(302)
                    self.send_header("Location", "/create?folder=" + quote(report.parent.name))
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                report_text = report.read_text(encoding="utf-8") if report.is_file() else ""
                if report.is_file() and ('id="lecture-title"' not in report_text
                                         or 'subtitle-report.js' not in report_text
                                         or '← Все лекции' in report_text):
                    folder = report.parent
                    root = folder if (folder / "manifest.json").is_file() else folder.parent
                    if (root / "manifest.json").is_file() and (root / "notes.json").is_file():
                        from .translate import refresh_reports
                        refresh_reports(root)
                report_root = report.parent if (report.parent / 'manifest.json').is_file() else report.parent.parent
                if report.is_file() and (report_root / "manifest.json").is_file():
                    if params.get("embedded") != ["1"]:
                        self.send_response(302)
                        self.send_header("Location", "/create?" + urlencode({"folder": report_root.name, "stage": "notes", **({"report": report.parent.name} if report_root != report.parent else {})}))
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    page = report.read_text(encoding="utf-8")
                    page = re.sub(r"<script>.*?</script>", '<script src="/studio-assets/report-embed.js"></script>', page, flags=re.DOTALL)
                    # Older generated reports retain their local assets; serve the current editor.
                    page = page.replace('src="assets/editor.js"', 'src="/studio-assets/editor.js"')
                    body = page.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
            return super().do_GET()
        try:
            folder = self.editor_folder()
            self.json_response(200, lecture_info(folder) if path.endswith("/title.json") else load_document(folder))
        except (ValueError, OSError) as exc:
            self.json_response(404, {"error": str(exc)})

    def do_POST(self):
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            return self.json_response(403, {"error": "Сохранение доступно из страницы отчёта"})
        path = urlsplit(self.path).path
        if path in ('/api/delete-version', '/api/delete-notes'):
            try:
                from .versions import delete_notes, delete_version
                length = int(self.headers.get('Content-Length', '0'))
                if self.headers.get_content_type() != 'application/json' or not 0 < length <= 4096:
                    raise ValueError('Недопустимый размер запроса')
                value = json.loads(self.rfile.read(length))
                if not isinstance(value, dict):
                    raise TypeError('Ожидается версия')
                result = (delete_notes(Path(self.directory), value.get('folder'), value.get('report', ''))
                          if path == '/api/delete-notes' else delete_version(Path(self.directory), value.get('folder')))
                return self.json_response(200, result)
            except (ValueError, OSError, TypeError) as exc:
                return self.json_response(400, {'error': str(exc)})
        if path in ('/api/construction-settings', '/api/construction-plan', '/api/notes-run'):
            try:
                from .construction import checked_folder, enqueue_notes, plan, snapshot_settings
                root = Path(self.directory).resolve()
                length = int(self.headers.get('Content-Length', '0'))
                if self.headers.get_content_type() != 'application/json' or not 0 < length <= 400_000:
                    raise ValueError('Недопустимый размер запроса')
                value = json.loads(self.rfile.read(length))
                if not isinstance(value, dict):
                    raise TypeError('Ожидаются настройки конспекта')
                if path == '/api/construction-settings':
                    return self.json_response(200, snapshot_settings(root, value))
                if path == '/api/construction-plan':
                    summary, _ = plan(checked_folder(root, value.get('folder')), value.get('settings'))
                    return self.json_response(200, summary)
                job = enqueue_notes(root, value.get('folder'), value.get('settings'))
                start_worker(root)
                return self.json_response(202, job)
            except (ValueError, OSError, TypeError, KeyError) as exc:
                return self.json_response(400, {'error': str(exc)})
        if path == "/api/prompts":
            try:
                from .prompt_settings import save
                length = int(self.headers.get('Content-Length', '0'))
                if self.headers.get_content_type() != 'application/json' or not 0 < length <= 400_000:
                    raise ValueError('Недопустимый размер запроса')
                return self.json_response(200, save(Path(self.directory), json.loads(self.rfile.read(length))))
            except (ValueError, OSError, TypeError) as exc:
                return self.json_response(400, {'error': str(exc)})
        if path in ("/api/speech-run", "/api/speech-names", "/api/speech-edit"):
            try:
                root = Path(self.directory).resolve()
                length = int(self.headers.get("Content-Length", "0"))
                limit = 2_000_000 if path == "/api/speech-edit" else 400_000
                if self.headers.get_content_type() != "application/json" or not 0 < length <= limit:
                    raise ValueError("Недопустимый размер JSON")
                value = json.loads(self.rfile.read(length))
                if not isinstance(value, dict):
                    raise TypeError("Ожидается объект JSON")
                if path == "/api/speech-edit":
                    from .speech import edit_utterance
                    return self.json_response(200, edit_utterance(root, value))
                if path.endswith("names"):
                    name = value["folder"]
                    if not name or Path(name).name != name:
                        raise ValueError("Неизвестная папка")
                    file = root / "output" / name / "speech.json"
                    result = read_json(file)
                    names = value["speaker_names"]
                    if not result or result["status"] != "done" or not isinstance(names, dict):
                        raise ValueError("Названия доступны после завершения")
                    if any(not isinstance(v, str) or len(v) > 100 for v in names.values()):
                        raise ValueError("Имя до 100 символов")
                    result["speaker_names"] = names
                    write_json(file, result)
                    return self.json_response(200, {"saved": True})
                if 'speech_only' in value and type(value['speech_only']) is not bool:
                    raise TypeError('Некорректный режим запуска речи')
                from .speech import enqueue_existing
                job = enqueue_existing(root, value["video"], value["engine"], value.get("title", ""),
                                       value.get("mode", "audio"), value.get("thinking", False), value.get('construction'))
                if 'speech_only' in value:
                    job['speech_only'] = value['speech_only']
                    write_json(jobs_dir(root) / job['id'] / 'job.json', job)
                start_worker(root)
                return self.json_response(202, job)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                return self.json_response(400, {"error": str(exc)})
        if path == "/api/translation-settings":
            try:
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Ожидается JSON")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError("Некорректный размер настройки")
                changes = json.loads(self.rfile.read(length))
                if not isinstance(changes, dict):
                    raise TypeError("Некорректные настройки")
                return self.json_response(200, translation_settings.save(Path(self.directory), changes))
            except (ValueError, OSError, TypeError) as exc:
                return self.json_response(400, {"error": str(exc)})
        if path == "/api/thinking":
            try:
                root = Path(self.directory).resolve()
                name = parse_qs(urlsplit(self.path).query).get("folder", [""])[0]
                if not name or Path(name).name != name:
                    raise ValueError("Неизвестная папка")
                folder = (root / "output" / name).resolve()
                folder.relative_to(root / "output")
                if not (folder / "manifest.json").is_file():
                    raise ValueError("Папка обработки не найдена")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024:
                    raise ValueError("Ожидается настройка рассуждений")
                value = json.loads(self.rfile.read(length))
                if not isinstance(value, dict) or not isinstance(value.get("thinking"), bool):
                    raise TypeError("thinking должен быть true или false")
                write_json(folder / "analysis-control.json", {"thinking": value["thinking"]})
                return self.json_response(200, value)
            except (ValueError, OSError, TypeError) as exc:
                return self.json_response(400, {"error": str(exc)})
        if path in ("/api/upload", "/api/retry"):
            try:
                root = Path(self.directory).resolve()
                params = parse_qs(urlsplit(self.path).query)
                if path == "/api/upload":
                    from .construction import read_snapshot
                    construction = read_snapshot(root, params['construction'][0]) if 'construction' in params else None
                    job = enqueue(root, self.rfile, int(self.headers.get("Content-Length", "0")),
                                  params.get("filename", [""])[0], params.get("title", [""])[0],
                                  params.get("thinking", ["false"])[0] == "true",
                                  params.get("mode", ["lecture"])[0], params.get("engine", ["gemini"])[0], construction)
                else:
                    id = params.get("id", [""])[0]
                    if not re.fullmatch(r"[0-9a-f]{32}", id):
                        raise ValueError("Неизвестное задание")
                    file = jobs_dir(root) / id / "job.json"
                    job = read_json(file)
                    if job is None or job.get("status") in ("queued", "running", "deleted"):
                        raise ValueError("Задание уже обрабатывается или не найдено")
                    job.update(status="queued", error=None)
                    write_json(file, job)
                start_worker(root)
                return self.json_response(202, job)
            except (ValueError, OSError, TypeError) as exc:
                return self.json_response(400, {"error": str(exc)})
        try:
            folder = self.editor_folder()
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                return self.json_response(413, {"error": "Допустимый размер заметки — до 2 МБ"})
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Ожидается JSON")
            value = json.loads(self.rfile.read(length))
            if urlsplit(self.path).path.endswith("/title.json"):
                if not isinstance(value, dict):
                    raise ValueError("Ожидается название лекции")
                return self.json_response(200, save_title(folder, value.get("title")))
            if (not isinstance(value, dict) or not isinstance(value.get("text"), str)
                    or not isinstance(value.get("revision"), str)):
                raise TypeError("Нужны текст и версия документа")
            self.json_response(200, save_document(folder, value["text"], value["revision"]))
        except EditConflict as exc:
            self.json_response(409, {"error": str(exc)})
        except (ValueError, TypeError, OSError) as exc:
            self.json_response(400, {"error": str(exc)})

    def send_head(self):
        self.byte_range = None
        path = self.translate_path(self.path)
        header = self.headers.get("Range")
        if not header or not os.path.isfile(path):
            return super().send_head()
        try:
            stream = open(path, "rb")  # noqa: SIM115 — do_GET/do_HEAD close the returned stream.
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return None
        stat = os.fstat(stream.fileno())
        modified = self.date_time_string(stat.st_mtime)
        if self.headers.get("If-Range") not in (None, modified):
            stream.close()
            return super().send_head()
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
        if not match:  # Ignore unsupported units and multiple ranges.
            stream.close()
            return super().send_head()
        first, last = match.groups()
        if first:
            start = int(first)
            end = min(int(last), stat.st_size - 1) if last else stat.st_size - 1
        else:
            length = int(last or 0)
            start, end = max(0, stat.st_size - length), stat.st_size - 1
            if not length:
                start = stat.st_size
        if start > end or start >= stat.st_size:
            stream.close()
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{stat.st_size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        self.byte_range = (start, end)
        stream.seek(start)
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{stat.st_size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Last-Modified", modified)
        self.end_headers()
        return stream

    def end_headers(self):
        if self.byte_range is None:
            self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def copyfile(self, source, outputfile):
        try:
            if self.byte_range is None:
                return super().copyfile(source, outputfile)
            remaining = self.byte_range[1] - self.byte_range[0] + 1
            while remaining:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                outputfile.write(chunk)
                remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Browsers cancel an earlier request when seeking elsewhere.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--directory", type=Path, default=Path.cwd())
    args = parser.parse_args()
    handler = partial(RangeRequestHandler, directory=str(args.directory.resolve()))
    with ThreadingHTTPServer((args.bind, args.port), handler) as server:
        print(f"Отчёты: http://localhost:{args.port}/output/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
