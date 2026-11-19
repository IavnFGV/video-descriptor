"""Persist the exact request and streamed response for later diagnosis."""

import json
import time
import uuid
from pathlib import Path

from .action_history import record


class RequestJournal:
    def __init__(self, root: Path, url: str, payload: dict, context: dict, task: str):
        self.folder = root / f"{time.time_ns()}-{task}-{uuid.uuid4().hex[:6]}"
        self.folder.mkdir(parents=True)
        self.write("request.json", {"url": url, "context": context, "payload": payload})
        self.write("result.json", {"status": "running"})
        self.stream = (self.folder / "events.jsonl").open("w", encoding="utf-8")
        self.parts = []
        self.thinking = []
        self.recording_folder = root.parent
        self.task = task
        self.model = payload.get('model')
        self.stage = context.get('stage')
        record('model_request_started', folder=self.recording_folder, request_id=self.folder.name,
               model=payload.get('model'), task=task, status='running')

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

    def retry(self, attempt, *, code):
        record('model_request_retry', folder=self.recording_folder, request_id=self.folder.name,
               model=self.model, stage=self.stage, task=self.task, status='waiting', attempt=attempt, code=code)

    def finish(self, status, error=None, *, code=None):
        self.stream.close()
        (self.folder / "response.txt").write_text("".join(self.parts), encoding="utf-8")
        (self.folder / "thinking.txt").write_text("".join(self.thinking), encoding="utf-8")
        self.write("result.json", {"status": status, "error": error,
                                   **({"http_status": code} if code is not None else {})})
        record('model_request_finished', folder=self.recording_folder, request_id=self.folder.name,
                task=self.task, status=status, received=sum(map(len, self.parts)),
                reason='request_error' if error else None, **({'code': code} if code is not None else {}))
