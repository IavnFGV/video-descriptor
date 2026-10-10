"""Read bounded live snapshots from the existing pipeline artifacts."""

import json
import re
from pathlib import Path
from urllib.parse import quote

from .jobs import read_json, video_url
from .library import lecture_info


def tail(path, limit=128 * 1024):
    try:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - limit))
            return stream.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def active_video(video):
    for folder in Path("/proc").iterdir():
        if folder.name.isdigit():
            try:
                args = (folder / "cmdline").read_bytes().split(b"\0")
                if b"video_descriptor" not in args and b"video_descriptor.translate" not in args:
                    continue
                cwd = (folder / "cwd").resolve()
                for arg in args:
                    if not arg or arg.startswith(b"-"):
                        continue
                    value = Path(arg.decode(errors="replace"))
                    path = value if value.is_absolute() else cwd / value
                    if path.resolve() == Path(video).resolve():
                        return True
                    if path.is_dir() and read_json(path / "manifest.json", {}).get("video") == video:
                        return True
            except OSError:
                continue
    return False


def processing_details(phase, state, speech_result, payload=None, recognition_settings=None):
    """Describe the current stage using only its recorded request settings."""
    titles = {1: "Проверка записи", 2: "Распознавание речи", 3: "Анализ изображения",
              4: "Создание конспекта", 5: "Сохранение отчёта", 6: "Перевод субтитров"}
    details = {"title": titles.get(phase, "Обработка"), "task": state.get("task", "—"),
               "parameters": [], "message": "Для этого этапа параметры модели не нужны.",
               "request_available": False, "supports_thinking": False}
    if phase == 2 and speech_result:
        speech_stage = speech_result.get("stage")
        details["task"] = speech_result.get("message", "Распознавание речи")
        if speech_stage == "diarization":
            details.update(title="Распознавание говорящих",
                           message="Для распознавания говорящих параметры не нужны.")
        elif speech_stage == "parallel":
            details.update(title="Распознавание речи и говорящих",
                           message="Для распознавания говорящих параметры не нужны.")
        elif speech_stage == "preparation":
            details["title"] = "Подготовка аудио"
        if speech_result.get("engine"):
            details["engine"] = speech_result["engine"]
        if speech_stage not in ("diarization", "preparation"):
            settings = recognition_settings or speech_result.get("recognition_parameters", {})
            details["parameters"] = [{"name": name, "value": value} for name, value in settings.items()]
            if settings:
                details["message"] = ("Параметры распознавания речи. Для распознавания говорящих параметры не нужны."
                                      if speech_stage == "parallel" else "Параметры текущего распознавания речи.")
            elif speech_stage != "parallel":
                details["message"] = "Обработчик ещё не опубликовал параметры распознавания речи."
        return details
    if phase not in (4, 6):
        return details
    if not payload:
        details["message"] = ("Результат этой задачи взят из кэша; нового запроса нет."
                              if state.get("request_state") == "из кэша"
                              else "Параметры появятся при отправке запроса для этой задачи.")
        return details
    details.update(request_available=True, message="Параметры отправленного запроса.")
    parameters = details["parameters"]
    if payload.get("model"):
        parameters.append({"name": "Модель", "value": payload["model"]})
    elif state.get("model"):
        parameters.append({"name": "Модель", "value": state["model"]})
    options = payload.get("options", payload.get("generationConfig", {}))
    for name, value in options.items():
        parameters.append({"name": name, "value": value})
    if "think" in payload:
        parameters.append({"name": "Рассуждения", "value": payload["think"]})
        details["supports_thinking"] = True
    return details


def snapshot(root, folder):
    manifest = read_json(folder / "manifest.json", {})
    if not manifest.get("video"):
        raise ValueError("Папка обработки не найдена")
    state = read_json(folder / "progress.json", {})
    speech_result = read_json(folder / "speech.json", {})
    construction_id = read_json(folder / 'construction-job.json', {}).get('id')
    construction_job = read_json(root / 'output' / 'jobs' / construction_id / 'job.json') if construction_id else None
    if speech_result and not state:
        state = {"stage": "[2/5] Аудио и распознавание", "message": speech_result.get("message", ""),
                 "model": speech_result.get("engine", "")}
    controls = read_json(folder / "analysis-control.json", {})
    log_file = folder / "run.log"
    if not log_file.exists() and speech_result.get("job_id"):
        log_file = root / "output" / "jobs" / speech_result["job_id"] / "run.log"
    lines = tail(log_file).splitlines()
    last = lines[-1] if lines else ""
    if not state:
        for key in ("этап", "блок", "задача", "модель"):
            match = re.search(rf"{key}=([^|]+)", last)
            if match:
                state[{"этап": "stage", "блок": "chunk", "задача": "task", "модель": "model"}[key]] = match[1].strip()
        state["message"] = last.rsplit(" | ", 1)[-1]
        for key, pattern in {"received": r"получено=(\d+)", "thinking": r"рассуждение=(\d+)",
                             "request_seconds": r"запрос (\d+) сек", "images": r"(\d+) карт\.",
                             "sent_chars": r"отправлено=(\d+)"}.items():
            match = re.search(pattern, last)
            if match:
                state[key] = int(match[1])
    if construction_job and (construction_job.get('status') == 'queued' or not (folder / 'progress.json').is_file()):
        state = {**state, 'stage': '[4/5] Конспект',
                 'message': 'Конспект в очереди' if construction_job.get('status') == 'queued' else 'Подготовка конспекта'}
    stage = state.get("stage", "")
    number = re.search(r"\[(\d)/5\]", stage)
    phase = int(number[1]) if number else 6 if "Перевод" in stage else 1
    speech = read_json(folder / "transcript.json")
    checkpoint = read_json(folder / "transcript.partial.json", {})
    if speech is None:
        speech = checkpoint.get("sources", []) or [
            {**row, "id": f"s{index}"} for index, row in enumerate(speech_result.get("segments", []), 1)]
    elif speech_result:
        segments = speech_result.get("segments", [])
        speech = [{**row, "speaker": segments[index].get("speaker", "unknown")}
                  if index < len(segments) else row for index, row in enumerate(speech)]
    edits = read_json(folder / "transcript-edits.json", {})
    if edits.get("segments"):
        speech = [{**row, "id": row.get("id", f"s{index}")}
                  for index, row in enumerate(edits["segments"], 1)]
    translations = {**read_json(folder / "translations.json", {}), **edits.get("translations", {})}
    speech = [{**row, "translation": translations.get(row["id"])} for row in speech]
    frames = read_json(folder / "frames.json")
    if frames is None:
        frames = read_json(folder / "frames.partial.json", [])
    live = read_json(folder / "notes-live.json")
    final = read_json(folder / "notes.json")
    provisional = False
    if live is None:
        live = final
    if live is None:
        # Older terminal processes still expose raw cached blocks; label them as drafts.
        live = {"notes": [], "sections": []}
        plans = sorted(folder.glob("chunk-plan-*.json"), key=lambda p: p.stat().st_mtime_ns)
        if plans:
            key = plans[-1].stem.removeprefix("chunk-plan-")
            blocks = {}
            for path in folder.glob(f"notes-{key}-*.json"):
                block = path.stem.split("-")[-1]
                if block not in blocks or path.stat().st_mtime_ns > blocks[block].stat().st_mtime_ns:
                    blocks[block] = path
            for key in sorted(blocks):
                data = read_json(blocks[key], {})
                live["notes"].extend(data.get("notes", []))
                live["sections"].extend(data.get("sections", []))
            provisional = bool(blocks)
    position = manifest.get("start", 0)
    block_end = None
    duration = manifest.get("processed_duration", speech_result.get("duration", 0))
    if phase == 2 and speech:
        position = speech_result.get("processed", speech[-1]["end"])
    elif phase == 3 and frames:
        position = frames[-1]["start"]
    elif phase in (4, 6):
        match = re.search(r"\[(\d+)–(\d+) сек\]", state.get("chunk", ""))
        span = re.search(r"(\d+)–(\d+) сек", state.get("span", ""))
        if span or match:
            position = float((span or match)[1])
            block_end = float((span or match)[2])
        else:
            match = re.search(r"блок=[^|]*\[(\d+)–(\d+) сек\]", last)
            if match:
                position = float(match[1])
                block_end = float(match[2])
    errors = read_json(folder / "analysis-errors.json", [])
    translation_errors = read_json(folder / "translation-errors.json", [])
    running = active_video(manifest["video"])
    if construction_job and construction_job.get('status') in ('queued', 'running'):
        running = True
    translation_progress = None
    if phase == 6:
        from .models import Source
        from .notes import group_sources
        groups = group_sources([Source.model_validate(item) for item in speech], 0, 90)
        current = int(state.get("chunk", "0/0").split("/")[0])
        failed = {item["block"] for item in translation_errors}
        historical = set(read_json(folder / "translation-error-history.json", [])) | failed
        blocks = []
        for index, group in enumerate(groups, 1):
            complete = all(item.id in translations for item in group)
            status = ("ready" if complete else "active" if running and index == current
                      else "error" if index in failed else "retry" if index in historical else "pending")
            blocks.append({"block": index, "status": status,
                           "retry": index in historical,
                           "start": min(item.start for item in group),
                           "end": max(item.end for item in group)})
        completed = sum(item["status"] == "ready" for item in blocks)
        translation_progress = {"total": len(blocks), "completed": completed,
                                "remaining": len(blocks) - completed,
                                "current": current, "blocks": blocks}
    ready = (folder / "report.html").is_file() and (not speech_result or (folder / "notes.json").is_file())
    done = ready and not running
    if done:
        position = manifest.get("start", 0) + duration
    visible_speech = speech if not running or construction_job and construction_job.get('status') == 'queued' else speech[-80:]
    visible_frames = frames[-12:]
    if phase in (4, 6) and block_end is not None and running and not (construction_job and construction_job.get('status') == 'queued'):
        visible_speech = [s for s in speech if s["end"] > position and s["start"] < block_end][-80:]
        visible_frames = [f for f in frames if f["end"] > position and f["start"] < block_end][-12:]
    request_dir = state.get("request_log")
    request_folder = Path(request_dir) if request_dir else None
    if (request_folder is None or not request_folder.is_dir()) and phase in (4, 6) and state.get("task") not in (None, "—"):
        requests = list((folder / "requests").glob("*/events.jsonl"))
        request_folder = max(requests, key=lambda p: p.stat().st_mtime_ns).parent if requests else None
    if phase not in (4, 6) or state.get("task") in (None, "—") or state.get("request_state") == "из кэша":
        request_folder = None
    content, thinking = [], []
    request_url = None
    request_payload = None
    if request_folder:
        try:
            request_folder.resolve().relative_to((folder / "requests").resolve())
            if (request_folder / "request.json").is_file():
                request_url = "/api/request?folder=" + quote(folder.name) + "&request=" + quote(request_folder.name)
                request_payload = read_json(request_folder / "request.json", {}).get("payload")
            for line in tail(request_folder / "events.jsonl", 64 * 1024).splitlines():
                try:
                    message = json.loads(line).get("message", {})
                    content.append(message.get("content", ""))
                    thinking.append(message.get("thinking", ""))
                except ValueError:
                    continue
        except ValueError:
            pass
    try:
        source_video = str(Path(manifest['video']).resolve().relative_to(root.resolve()))
    except ValueError:
        source_video = None
    report_variants = []
    for report_folder in [folder, *sorted(path for path in folder.iterdir() if path.is_dir())]:
        if (report_folder / 'report.html').is_file() and ((report_folder / 'notes.json').is_file() or report_folder != folder):
            try:
                report_folder.resolve().relative_to(folder.resolve())
            except ValueError:
                continue
            relative = report_folder.relative_to(root / 'output').as_posix()
            report_variants.append({'name': '' if report_folder == folder else report_folder.name,
                                    'url': '/output/' + quote(relative, safe='/') + '/report.html'})
    previous_report_url = None
    previous = manifest.get('version_of')
    if previous and Path(previous).name == previous and not (folder / 'notes-deleted.json').exists():
        previous_folder = root / 'output' / previous
        if (previous_folder / 'report.html').is_file() and (previous_folder / 'notes.json').is_file():
            previous_report_url = '/output/' + quote(previous) + '/report.html'
    return {"folder": folder.name, "filename": Path(manifest["video"]).name,
            "display_title": lecture_info(folder)["display"],
            "title": lecture_info(folder)["title"], "source_video": source_video,
            "previous_report_url": previous_report_url, "report_variants": report_variants,
            "speech_engine": speech_result.get("engine"),
            "video_url": video_url(root, manifest["video"]), "duration": duration,
            "start": manifest.get("start", 0), "position": position,
            "translation_progress": translation_progress,
            "phase": phase, "done": done, "running": running, "status": state,
            "processing": processing_details(phase, state, speech_result, request_payload,
                                             read_json(folder / "recognition-settings.json", {})),
            "skipped_steps": [{"phase": 3, "reason": "Пропущено для этой записи: анализ изображения отключён."}] if manifest.get("mode") == "audio" else [],
            "skip_images": manifest.get("mode") == "audio",
            "speaker_names": speech_result.get("speaker_names", {}),
            "speech_editor_url": "/create?folder=" + quote(folder.name) if speech else None,
            "subtitle_url": "/api/subtitles?folder=" + quote(folder.name) + "&language=original" if speech else None,
            "translation_url": "/api/subtitles?folder=" + quote(folder.name) + "&language=ru" if translations else None,
            "speaker_notice": speech_result.get("speaker_notice", ""),
            "job": construction_job or (read_json(root / "output" / "jobs" / speech_result["job_id"] / "job.json") if speech_result.get("job_id") else None),
            "has_ready_transcript": speech_result.get('status') == 'done' or (folder / 'transcript.json').is_file(),
            "construction_settings": read_json(folder / 'construction-settings.json'),
            "construction_plan": read_json(folder / 'construction-plan.json'),
            "construction_result_url": '/output/' + quote(folder.name) + '/construction-result.md' if (folder / 'construction-result.md').is_file() else None,
            "has_notes": bool(report_variants or any((folder / name).is_file() for name in (
                'notes.json', 'notes-live.json', 'notes.md', 'notes.user.md',
                'editor-default.md', 'construction-result.md', 'construction-plan.json'))
                or any(path.name != 'notes-deleted.json' for path in folder.glob('notes-*.json'))
                or any(folder.glob('chunk-plan-*.json'))),
            "notes_deleted": (folder / 'notes-deleted.json').is_file() and not (folder / 'notes.json').is_file(),
            "needs_notes": bool(speech_result or (folder / "transcript.json").is_file()) and not (folder / "notes.json").is_file(),
            "speech": visible_speech, "speech_count": len(speech), "frames": [
                {**frame, "image_url": "/output/" + quote(folder.name) + "/" + quote(frame["image"])}
                for frame in visible_frames if frame.get("image")],
            "frame_count": len(frames), "notes": live.get("notes", []),
            "sections": live.get("sections", []), "provisional": provisional,
            "response": "".join(content)[-8000:], "thinking": "".join(thinking)[-8000:],
            "request_url": request_url,
            "thinking_next": controls.get("thinking", state.get("thinking_enabled", False)),
            "errors": errors + translation_errors, "log": lines[-8:],
            "report_url": "/output/" + quote(folder.name) + "/report.html" if ready else None}


def runs(root):
    output = root / "output"
    items = []
    if output.exists():
        for folder in output.iterdir():
            manifest = read_json(folder / "manifest.json", {})
            if manifest.get("video"):
                info = lecture_info(folder)
                ready = ((folder / "report.html").is_file()
                         and (not (folder / "speech.json").is_file() or (folder / "notes.json").is_file()))
                items.append({"folder": folder.name, "filename": info['display'],
                              "video": manifest['video'], "video_url": video_url(root, root / manifest['video']), "ready": ready,
                              "kind": "Конспект" if (folder / "notes.json").is_file() or folder.name.startswith('notes-') else "Речь",
                              "created": manifest.get('version_created', (folder / 'manifest.json').stat().st_mtime)})
    return sorted(items, key=lambda item: item["folder"], reverse=True)
