"""Check the development environment without downloading or loading models."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import sys
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama", action="store_true", help="Query configured Ollama server")
    parser.add_argument("--whisper", action="store_true", help="Check the Windows NPU worker")
    args = parser.parse_args()
    failures = []
    print(f"Python: {sys.version.split()[0]}")
    if sys.version_info < (3, 11):  # noqa: UP036 — standalone environment check.
        failures.append("Python 3.11+ required")
    for command in ("ffmpeg", "ffprobe", "tesseract"):
        path = shutil.which(command)
        print(f"{command}: {path or 'MISSING'}")
        if not path:
            failures.append(command)
    for package in ("pydantic", "typer", "requests", "faster-whisper", "av", "opencv-python-headless"):
        try:
            version = importlib.metadata.version(package)
            print(f"{package}: {version}")
            if package == "av" and int(version.split(".")[0]) >= 19:
                failures.append("PyAV 19+ incompatible with this Whisper profile; install av<19")
        except importlib.metadata.PackageNotFoundError:
            print(f"{package}: MISSING")
            failures.append(package)
    if args.ollama:
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
        try:
            with urllib.request.urlopen(f"{base_url}/api/tags", timeout=5) as response:
                payload = json.load(response)
            names = [model["name"] for model in payload["models"]]
            print("Ollama models: " + (", ".join(names) or "none installed"))
            selected = os.environ.get("OLLAMA_MODEL", "").strip()
            if selected and selected not in names:
                failures.append(f"Configured Ollama model not found: {selected}")
            elif not selected:
                print("Set OLLAMA_MODEL in .devcontainer/runtime.env to an installed model.")
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
            print(f"Ollama check failed: {exc}")
            failures.append("Ollama connection")
    if args.whisper:
        base = os.environ.get("WHISPER_HTTP_URL", "http://host.docker.internal:8765").rstrip("/")
        try:
            with urllib.request.urlopen(base + "/health", timeout=5) as response:
                info = json.load(response)
            if (info.get("protocol"), info.get("device"), info.get("model")) != (1, "NPU", "base.en"):
                raise ValueError("Expected protocol=1, device=NPU, model=base.en")
            print(f"Whisper worker: {base}, NPU, {info['model']}, {info.get('pipeline')}")
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
            print(f"Whisper check failed: {exc}; start start_whisper_npu.ps1 in Windows")
            failures.append("Windows NPU worker")
    if failures:
        print("Checks failed: " + ", ".join(failures))
        return 1
    print("Environment checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
