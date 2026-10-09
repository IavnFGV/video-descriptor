"""Persist the exact request and streamed response for later diagnosis."""

import json
import time
import uuid
from pathlib import Path


class RequestJournal:
    def __init__(self, root: Path, url: str, payload: dict, context: dict, task: str):
        self.folder = root / f"{time.time_ns()}-{task}-{uuid.uuid4().hex[:6]}"
        self.folder.mkdir(parents=True)
        self.write("request.json", {"url": url, "context": context, "payload": payload})
        self.write("result.json", {"status": "running"})
        self.stream = (self.folder / "events.jsonl").open("w", encoding="utf-8")
        self.parts = []
        self.thinking = []

    def write(self, name, value):
        path = self.folder / name
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def event(self, value):
        message = value.get("message", {})
        self.parts.append(message.get("content", ""))
        self.thinking.append(message.get("thinking", ""))

    def raw(self, line):
        self.stream.write(line.decode("utf-8", errors="replace") + "\n")
        self.stream.flush()

    def finish(self, status, error=None):
        self.stream.close()
        (self.folder / "response.txt").write_text("".join(self.parts), encoding="utf-8")
        (self.folder / "thinking.txt").write_text("".join(self.thinking), encoding="utf-8")
        self.write("result.json", {"status": status, "error": error})
