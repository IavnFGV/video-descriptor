"""Small disk-backed upload queue, processed by an independent local worker."""

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_json(path, fallback=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def jobs_dir(root):
    folder = root / "output" / "jobs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def enqueue(root, stream, length, filename, title="", thinking=False):
    filename = Path(filename).name
    if not filename or Path(filename).suffix.lower() not in {".mp4", ".mkv", ".mov", ".webm"}:
        raise ValueError("Выберите видео MP4, MKV, MOV или WebM")
    if not 0 < length <= 4 * 1024**3:
        raise ValueError("Размер видео должен быть от 1 байта до 4 ГБ")
    if len(title) > 200:
        raise ValueError("Название — до 200 символов")
    id = uuid.uuid4().hex
    video_dir = root / "data" / "uploads" / id
    video_dir.mkdir(parents=True)
    video = video_dir / filename
    try:
        with video.open("wb") as target:
            remaining = length
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("Загрузка оборвалась; видео не добавлено в очередь")
                target.write(chunk)
                remaining -= len(chunk)
    except BaseException:
        video.unlink(missing_ok=True)
        video_dir.rmdir()
        raise
    folder = jobs_dir(root) / id
    folder.mkdir()
    job = {"id": id, "video": str(video), "filename": filename, "title": title,
           "thinking": thinking, "status": "queued", "created": time.time(), "folder": None}
    write_json(folder / "job.json", job)
    return job


def start_worker(root):
    with (jobs_dir(root) / "worker.log").open("a") as log:
        subprocess.Popen([sys.executable, "-u", "-m", "video_descriptor.jobs", str(root)],
                         cwd=root, stdin=subprocess.DEVNULL, stdout=log,
                         stderr=subprocess.STDOUT, start_new_session=True)


def pipeline_busy():
    """Respect existing terminal runs on this devcontainer, as well as queued jobs."""
    for folder in Path("/proc").iterdir():
        if not folder.name.isdigit() or int(folder.name) == os.getpid():
            continue
        try:
            args = (folder / "cmdline").read_bytes().split(b"\0")
            if b"video_descriptor" in args or b"video_descriptor.translate" in args:
                return True
        except OSError:
            continue
    return False


def find_result(root, video):
    candidates = []
    for folder in (root / "output").iterdir():
        manifest = read_json(folder / "manifest.json", {})
        if manifest.get("video") == video:
            candidates.append(folder)
    return max(candidates, key=lambda f: (f / "manifest.json").stat().st_mtime_ns) if candidates else None


def run_job(root, folder, job):
    job.update(status="running", started=time.time(), error=None)
    write_json(folder / "job.json", job)
    try:
        with (folder / "run.log").open("a") as log:
            command = [sys.executable, "-u", "-m", "video_descriptor", job["video"],
                       "--model", "qwen3.5:9b", "--frame-strategy", "scene", "--chunk-strategy", "slides"]
            if job["thinking"]:
                command.append("--think")
            code = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, check=False).returncode
            result = find_result(root, job["video"])
            if result:
                job["folder"] = result.name
                write_json(folder / "job.json", job)
            if code:
                raise RuntimeError(f"Обработка остановилась, код {code}; подробности в журнале")
            if result is None:
                raise RuntimeError("Папка результата не найдена")
            if job["title"]:
                from .library import save_title
                save_title(result, job["title"])
            code = subprocess.run([sys.executable, "-u", "-m", "video_descriptor.translate",
                                   str(result), "--model", "qwen3.5:9b"], cwd=root,
                                  stdout=log, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, check=False).returncode
            if code:
                raise RuntimeError(f"Перевод остановился, код {code}; конспект уже доступен")
        job["status"] = "done"
    except (OSError, RuntimeError) as exc:
        job.update(status="error", error=str(exc))
    job["finished"] = time.time()
    write_json(folder / "job.json", job)


def worker(root, stay_alive=True):
    with (jobs_dir(root) / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        # A terminated worker leaves an explicit error, rather than a false running state.
        for path in jobs_dir(root).glob("*/job.json"):
            job = read_json(path, {})
            if job.get("status") == "running":
                job.update(status="error", error="Рабочий процесс был прерван; кэш сохранён")
                write_json(path, job)
        while True:
            queued = [(path, read_json(path, {})) for path in jobs_dir(root).glob("*/job.json")]
            queued = sorted(((p, j) for p, j in queued if j.get("status") == "queued"),
                            key=lambda item: item[1]["created"])
            if not queued:
                if not stay_alive:
                    return
                time.sleep(2)
                continue
            if pipeline_busy():
                time.sleep(10)
                continue
            path, job = queued[0]
            run_job(root, path.parent, job)


def video_url(root, video):
    try:
        return "/" + quote(str(Path(video).resolve().relative_to(root.resolve())))
    except ValueError:
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    worker(parser.parse_args().root.resolve())
