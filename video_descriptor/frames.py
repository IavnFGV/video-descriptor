"""FFmpeg scene selection; OCR runs only on selected images."""

import json
import re
from pathlib import Path

from .models import Source


def save_frame_checkpoint(folder, sources):
    path = folder.parent / "frames.partial.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps([s.model_dump() for s in sources], ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def selection_filter(scan_interval: float, threshold: float, max_gap: float) -> str:
    return (f"fps=1/{scan_interval},"
            f"select='isnan(prev_selected_t)+gt(scene,{threshold})"
            f"+gte(t-prev_selected_t,{max_gap})'")


def parse_selection(text: str) -> list[dict]:
    frames = []
    for line in text.splitlines():
        match = re.search(r"pts_time:([\d.eE+-]+)", line)
        if match:
            frames.append({"time": float(match[1]), "scene_score": 0.0})
        elif line.startswith("lavfi.scene_score=") and frames:
            frames[-1]["scene_score"] = float(line.split("=", 1)[1])
    return frames


def extract_scene_frames(video: Path, folder: Path, start: float, duration: float,
                         language: str, log, scan_interval=1.0, threshold=0.01, max_gap=60.0):
    from .media import run

    folder.mkdir(exist_ok=True)
    filter_graph = selection_filter(scan_interval, threshold, max_gap)
    log(f"FFmpeg: отбор по изменениям, проверка раз в {scan_interval:g} сек, "
        f"порог {threshold:g}, контрольный интервал {max_gap:g} сек")
    # stdout avoids embedding a Windows drive colon/backslashes in FFmpeg's filter grammar.
    metadata = run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y",
                    "-ss", str(start), "-i", str(video), "-t", str(duration), "-an",
                    "-vf", filter_graph + ",metadata=print:file=-",
                    "-fps_mode", "vfr", "-q:v", "2", str(folder / "f%05d.jpg")])
    selected = [item for item in parse_selection(metadata) if 0 <= item["time"] < duration]
    if not selected:
        raise RuntimeError("FFmpeg не извлёк ни одного кадра; уменьшите --scan-interval")
    log(f"FFmpeg: отобрано {len(selected)} кадров; OCR читает только их")
    records, sources = [], []
    for index, item in enumerate(selected):
        timestamp = start + item["time"]
        image = folder / f"f{index + 1:05d}.jpg"
        if not image.is_file():
            raise RuntimeError(f"FFmpeg не сохранил выбранный кадр {image}")
        reason = ("initial" if index == 0 else
                  "change" if item["scene_score"] > threshold else "heartbeat")
        records.append({"id": image.stem, "start": timestamp,
                        "scene_score": item["scene_score"], "reason": reason})
        text = run(["tesseract", str(image), "stdout", "-l", language, "--psm", "11"])
        end = start + selected[index + 1]["time"] if index + 1 < len(selected) else start + duration
        sources.append(Source(id=image.stem, start=timestamp, end=end, text=text.strip(),
                              image=f"frames/{image.name}"))
        save_frame_checkpoint(folder, sources)
        log(f"Экран/OCR: {index + 1}/{len(selected)} выбранных кадров, "
            f"позиция {timestamp:.1f} сек ({reason})")
    (folder.parent / "frame-selection.json").write_text(json.dumps({
        "strategy": "scene", "filter": filter_graph, "scan_interval": scan_interval,
        "scene_threshold": threshold, "max_gap": max_gap, "frames": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return sources
