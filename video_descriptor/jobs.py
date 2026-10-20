"""Small disk-backed upload queue, processed by an independent local worker."""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from .action_history import record
from .platform_support import environment_python, lock_file, subprocess_options, windows_processes


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


def enqueue(root, stream, length, filename, title="", thinking=False, mode="lecture", engine="gemini", construction=None,
            *, language='auto', speech_only=False, device_plan=None):
    if engine == 'whisper-local' and not isinstance(device_plan, dict):
        raise ValueError('Для локального backend нужен сохранённый план устройств')
    if language not in {'auto', 'en', 'ru', 'uk'}:
        raise ValueError('Выберите язык: auto, en, ru или uk')
    if type(speech_only) is not bool or (speech_only and mode != 'audio'):
        raise ValueError('Режим только речи доступен для audio')
    if mode not in {"lecture", "audio"}:
        raise ValueError("Неизвестный режим")
    if construction is not None:
        from .construction import validate, validate_provider
        construction = validate(construction)
        validate_provider(root, construction)
    from .speech import EXTENSIONS, validate_engine
    if mode == "audio" or construction is not None:
        validate_engine(root, engine)
    filename = Path(filename).name
    allowed = EXTENSIONS if mode == "audio" else {".mp4", ".mkv", ".mov", ".webm"}
    if not filename or Path(filename).suffix.lower() not in allowed:
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
           "thinking": thinking, "mode": mode, "engine": engine,
           "status": "queued", "created": time.time(), "folder": None}
    job.update(language=language, speech_only=speech_only)
    if device_plan is not None:
        job['device_plan'] = device_plan
    if construction is not None:
        job['construction'] = construction
    write_json(folder / "job.json", job)
    record('job_added', job_id=id, stage='speech', language=language)
    return job


def start_worker(root):
    if os.getenv('VIDEO_DESCRIPTOR_MANAGED_WORKER') == '1':
        return  # The container supervisor owns the persistent worker.
    with (jobs_dir(root) / "worker.log").open("a") as log:
        subprocess.Popen([sys.executable, "-u", "-m", "video_descriptor.jobs", str(root)],
                         cwd=root, stdin=subprocess.DEVNULL, stdout=log,
                         stderr=subprocess.STDOUT, **subprocess_options())


def pipeline_busy():
    """Respect existing terminal runs on this devcontainer, as well as queued jobs."""
    if os.name == 'nt':
        names = {'video_descriptor', 'video_descriptor.translate', 'video_descriptor.construction'}
        return any(names.intersection(args) for args, _ in windows_processes())
    for folder in Path("/proc").iterdir():
        if not folder.name.isdigit() or int(folder.name) == os.getpid():
            continue
        try:
            args = (folder / "cmdline").read_bytes().split(b"\0")
            if any(name in args for name in (b"video_descriptor", b"video_descriptor.translate", b"video_descriptor.construction")):
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


class JobStopped(RuntimeError):
    pass


def check_stop(folder, process=None):
    if not (folder / 'stop-request.json').exists():
        return
    if process is not None and process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           **subprocess_options())
        else:
            import signal
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=15)
    raise JobStopped('Остановлено по вашей команде. Сохранённый текст и кэш доступны.')


def run_process(folder, command, **kwargs):
    kwargs.pop('check', None)
    check_stop(folder)
    kwargs = {**subprocess_options(), **kwargs}
    with subprocess.Popen(command, **kwargs) as process:
        while process.poll() is None:
            check_stop(folder, process)
            time.sleep(.2)
        check_stop(folder)
        return subprocess.CompletedProcess(command, process.returncode)


def stop_legacy_diarization(root, folder, job):
    import psutil
    script = str((Path(__file__).resolve().parents[1] / 'windows-app' / 'diarization_worker.py').resolve())
    output = str((root / 'output' / job['folder'] / 'diarization-result.json').resolve())
    for process in psutil.process_iter(['cmdline']):
        try:
            args = process.info['cmdline'] or []
            if script not in args or '--output' not in args or args[args.index('--output') + 1] != output:
                continue
            children = process.children(recursive=True)
            for child in reversed(children):
                child.kill()
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, IndexError):
            continue
    for _ in range(150):
        current = read_json(folder / 'job.json', {})
        if current.get('status') not in {'queued', 'running'}:
            if current.get('status') == 'error':
                current.update(cancelled=True, error='Остановлено по вашей команде. Исходная расшифровка сохранена.')
                write_json(folder / 'job.json', current)
            return
        time.sleep(.1)


def request_stop(root, job_id):
    if not isinstance(job_id, str) or len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        raise ValueError('Некорректное задание')
    folder = jobs_dir(root) / job_id
    job = read_json(folder / 'job.json')
    if not job:
        raise ValueError('Задание не найдено')
    if job.get('status') not in {'queued', 'running'}:
        return job
    write_json(folder / 'stop-request.json', {'requested': time.time()})
    if job['status'] == 'running' and job.get('task') == 'diarize' and not job.get('cancellation_version'):
        # Adopt a pre-upgrade diarization worker by its exact script and output arguments.
        import threading
        threading.Thread(target=stop_legacy_diarization, args=(root, folder, job), daemon=True).start()

    if job['status'] == 'queued':
        job.update(status='error', cancelled=True, error='Остановлено по вашей команде.', finished=time.time())
        write_json(folder / 'job.json', job)
    return job


def run_job(root, folder, job):
    if (folder / 'stop-request.json').exists():
        return
    job.pop('cancelled', None)
    job.update(status="running", started=time.time(), error=None, cancellation_version=1)
    write_json(folder / "job.json", job)
    stage = job.get('task', 'notes' if job.get('mode') == 'notes' else 'speech')
    record('job_started', job_id=job['id'], stage=stage, requested=job.get('device_plan', {}).get('requested'))
    try:
        with (folder / "run.log").open("a") as log:
            if job.get('mode') == 'postprocess':
                from .postprocess import run
                run(root, folder, job, log)
                check_stop(folder)
                job.update(status='done', finished=time.time())
                write_json(folder / 'job.json', job)
                record('job_finished', job_id=job['id'], stage=stage, status='done')
                return
            if job.get('mode') == 'notes':
                from .ollama_connection import base_url as ollama_base_url
                from .ollama_connection import job_environment
                settings = folder / 'construction.json'
                write_json(settings, job['construction'])
                result = root / 'output' / job['folder']
                code = run_process(folder, [sys.executable, '-u', '-m', 'video_descriptor.construction',
                                       str(root), str(result), str(settings)], cwd=root, stdout=log,
                                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, check=False,
                                      env=job_environment(job.get('ollama_url') or ollama_base_url(root))).returncode
                if code:
                    error = read_json(result / 'construction-error.json', {}).get('error', 'См. журнал')
                    raise RuntimeError('Конспект остановлен: ' + error)
                check_stop(folder)
                job.update(status='done', finished=time.time())
                write_json(folder / 'job.json', job)
                record('job_finished', job_id=job['id'], stage='notes', status='done')
                return
            if job.get("mode") == "audio" or job.get("construction"):
                completed = read_json(root / "output" / job["folder"] / "speech.json", {}) if job.get("folder") else {}
                environment = ".venv-diarization-xpu" if job["engine"].endswith("-xpu") else ".venv-diarization"
                python = environment_python(root, environment)
                if completed.get("status") != "done" and job["engine"].endswith("-xpu") and not python.exists():
                    raise RuntimeError("Не подготовлено отдельное Python-окружение Intel GPU/XPU. "
                                       "Выберите Whisper small NPU без голосов или настройте диаризацию.")
                executable = str(python) if "diarization" in job["engine"] and python.exists() else sys.executable
                code = 0
                if completed.get("status") != "done":
                    code = run_process(folder, [executable, "-u", "-m", "video_descriptor.speech",
                                           str(folder / "job.json")], cwd=root, stdout=log,
                                          stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, check=False,
                                          env={**os.environ, 'SPEECH_LANGUAGE': job.get('language', 'auto')}).returncode
                    updated = read_json(folder / "job.json", {})
                    job["folder"] = updated.get("folder")
                if code:
                    failure = read_json(root / "output" / job["folder"] / "speech.json", {}) if job.get("folder") else {}
                    raise RuntimeError(failure.get("message") or
                                       "Распознавание прервано из-за ошибки обработчика. "
                                       "Уже сохранённый текст доступен; повторите запуск после подготовки распознавания.")
            if job.get('speech_only'):
                check_stop(folder)
                job.update(status='done', finished=time.time())
                write_json(folder / 'job.json', job)
                record('job_finished', job_id=job['id'], stage='speech', status='done')
                return
            command = [sys.executable, "-u", "-m", "video_descriptor", job["video"],
                       "--model", os.getenv('OLLAMA_MODEL', 'qwen3.5:9b'), "--frame-strategy", "scene", "--chunk-strategy", "slides"]
            if job.get("mode") == "audio":
                command.append("--audio-only")
            if job.get("folder") and (root / "output" / job["folder"] / "speech.json").is_file():
                command.extend(["--speech-result", str(root / "output" / job["folder"] / "speech.json")])
            if job["thinking"]:
                command.append("--think")
            if job.get('construction'):
                command.append('--skip-notes')
            code = run_process(folder, command, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, check=False).returncode
            result = root / "output" / job["folder"] if job.get("folder") else find_result(root, job["video"])
            if result:
                job["folder"] = result.name
                write_json(folder / "job.json", job)
            if code:
                raise RuntimeError(f"Обработка остановилась, код {code}; подробности в журнале")
            if result is None:
                raise RuntimeError("Папка результата не найдена")
            if job.get('construction'):
                settings = folder / 'construction.json'
                write_json(settings, job['construction'])
                write_json(result / 'construction-job.json', {'id': job['id']})
                (result / 'construction-error.json').unlink(missing_ok=True)
                code = run_process(folder, [sys.executable, '-u', '-m', 'video_descriptor.construction',
                                       str(root), str(result), str(settings)], cwd=root, stdout=log,
                                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, check=False).returncode
                if code:
                    error = read_json(result / 'construction-error.json', {}).get('error', 'См. журнал')
                    raise RuntimeError('Конспект остановлен: ' + error)
            if job["title"]:
                from .library import save_title
                save_title(result, job["title"])
            code = run_process(folder, [sys.executable, "-u", "-m", "video_descriptor.translate",
                                   str(result), "--model", os.getenv('OLLAMA_MODEL', 'qwen3.5:9b')], cwd=root,
                                  stdout=log, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, check=False).returncode
            if code:
                raise RuntimeError(f"Перевод остановился, код {code}; конспект уже доступен")
        check_stop(folder)
        job["status"] = "done"
    except (OSError, RuntimeError) as exc:
        updated = read_json(folder / "job.json", {})
        job["folder"] = updated.get("folder", job.get("folder"))
        stopped = (folder / "stop-request.json").exists()
        job.update(status="error", cancelled=stopped, error=("Остановлено по вашей команде. Сохранённый текст и кэш доступны." if stopped else str(exc)))
        if stopped and job.get('folder'):
            speech_path = root / 'output' / job['folder'] / 'speech.json'
            speech = read_json(speech_path, {})
            if speech.get('status') in {'queued', 'running', 'error'}:
                speech.update(status='error', cancelled=True, message=job['error'])
                write_json(speech_path, speech)
        record('job_failed', job_id=job['id'], stage=stage, status='error', reason=type(exc).__name__)
    job["finished"] = time.time()
    write_json(folder / "job.json", job)


def worker(root, stay_alive=True):
    with (jobs_dir(root) / "worker.lock").open("a") as lock:
        try:
            lock_file(lock)
        except BlockingIOError:
            return
        # A terminated worker leaves an explicit error, rather than a false running state.
        for path in jobs_dir(root).glob("*/job.json"):
            job = read_json(path, {})
            if job.get("status") == "running":
                job.update(status="error", error="Рабочий процесс был прерван; кэш сохранён")
                write_json(path, job)
        idle_since = time.monotonic()
        while True:
            queued = [(path, read_json(path, {})) for path in jobs_dir(root).glob("*/job.json")]
            queued = sorted(((p, j) for p, j in queued if j.get("status") == "queued"),
                            key=lambda item: item[1]["created"])
            if not queued:
                if not stay_alive or (os.getenv('VIDEO_DESCRIPTOR_MANAGED_WORKER') != '1'
                                      and time.monotonic() - idle_since > 30):
                    return
                time.sleep(2)
                continue
            if pipeline_busy():
                time.sleep(10)
                continue
            path, job = queued[0]
            run_job(root, path.parent, job)
            idle_since = time.monotonic()


def video_url(root, video):
    try:
        return "/" + quote(Path(video).resolve().relative_to(root.resolve()).as_posix())
    except ValueError:
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    worker(parser.parse_args().root.resolve())
