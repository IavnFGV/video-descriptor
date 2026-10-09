"""Reuse speech when only frame selection changes; keep analysis folders isolated."""

import hashlib
import json
import os
import shutil
from pathlib import Path


def cache_digest(identity: dict) -> str:
    """Equal numeric settings must select the same folder (15 == 15.0)."""
    def normalize(value):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value
    return hashlib.sha256(json.dumps(normalize(identity), sort_keys=True).encode()).hexdigest()[:10]


def reuse_speech(folder: Path, identity: dict, log):
    if (folder / "audio.wav").exists() or (folder / "transcript.json").exists():
        return
    keys = ("video", "size", "mtime", "start", "duration", "whisper", "language")
    candidates = []
    for other in folder.parent.iterdir():
        manifest = other / "manifest.json"
        if other == folder or not manifest.is_file():
            continue
        data = json.loads(manifest.read_text())
        if all(data.get(key) == identity.get(key) for key in keys):
            candidates.append(other)
    candidates.sort(key=lambda p: ((p / "transcript.json").exists(),
                                  (p / "manifest.json").stat().st_mtime_ns), reverse=True)
    for other in candidates:
        audio = other / "audio.wav"
        if not audio.exists():
            continue
        target = folder / "audio.wav"
        try:
            os.link(audio, target)
        except OSError:
            shutil.copy2(audio, target)
        if (other / "transcript.json").exists():
            shutil.copy2(other / "transcript.json", folder / "transcript.json")
            if (other / "translations.json").exists():
                shutil.copy2(other / "translations.json", folder / "translations.json")
        elif (other / "transcript.partial.json").exists():
            state = json.loads((other / "transcript.partial.json").read_text())
            # The WAV bytes/stat are preserved, only its cache location changes.
            state["identity"]["audio"] = str(target.resolve())
            (folder / "transcript.partial.json").write_text(json.dumps(state), encoding="utf-8")
        log(f"Кэш речи переиспользован из {other.name}; смена отбора кадров не сбрасывает Whisper")
        return
