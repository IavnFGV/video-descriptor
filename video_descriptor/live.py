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


def snapshot(root, folder):
    manifest = read_json(folder / "manifest.json", {})
    if not manifest.get("video"):
        raise ValueError("Папка обработки не найдена")
    state = read_json(folder / "progress.json", {})
    controls = read_json(folder / "analysis-control.json", {})
    lines = tail(folder / "run.log").splitlines()
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
    stage = state.get("stage", "")
    number = re.search(r"\[(\d)/5\]", stage)
    phase = int(number[1]) if number else 6 if "Перевод" in stage else 1
    speech = read_json(folder / "transcript.json")
    checkpoint = read_json(folder / "transcript.partial.json", {})
    if speech is None:
        speech = checkpoint.get("sources", [])
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
    duration = manifest.get("processed_duration", 0)
    if phase == 2 and speech:
        position = speech[-1]["end"]
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
    ready = (folder / "report.html").is_file()
    done = ready and not running
    if done:
        position = manifest.get("start", 0) + duration
    visible_speech, visible_frames = speech[-80:], frames[-12:]
    if phase in (4, 6) and block_end is not None and not done:
        visible_speech = [s for s in speech if s["end"] > position and s["start"] < block_end][-80:]
        visible_frames = [f for f in frames if f["end"] > position and f["start"] < block_end][-12:]
    request_dir = state.get("request_log")
    request_folder = Path(request_dir) if request_dir else None
    if request_folder is None or not request_folder.is_dir():
        requests = list((folder / "requests").glob("*/events.jsonl"))
        request_folder = max(requests, key=lambda p: p.stat().st_mtime_ns).parent if requests else None
    content, thinking = [], []
    request_url = None
    if request_folder:
        try:
            request_folder.resolve().relative_to((folder / "requests").resolve())
            if (request_folder / "request.json").is_file():
                request_url = "/api/request?folder=" + quote(folder.name) + "&request=" + quote(request_folder.name)
            for line in tail(request_folder / "events.jsonl", 64 * 1024).splitlines():
                try:
                    message = json.loads(line).get("message", {})
                    content.append(message.get("content", ""))
                    thinking.append(message.get("thinking", ""))
                except ValueError:
                    continue
        except ValueError:
            pass
    return {"folder": folder.name, "filename": Path(manifest["video"]).name,
            "display_title": lecture_info(folder)["display"],
            "video_url": video_url(root, manifest["video"]), "duration": duration,
            "start": manifest.get("start", 0), "position": position,
            "phase": phase, "done": done, "running": running, "status": state,
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
            if (manifest.get("video") and manifest.get("duration") is None and manifest.get("start", 0) == 0
                    and ((folder / "report.html").is_file() or active_video(manifest["video"]))):
                items.append({"folder": folder.name, "filename": Path(manifest["video"]).name,
                              "ready": (folder / "report.html").is_file()})
    return sorted(items, key=lambda item: item["folder"], reverse=True)
