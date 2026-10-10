"""A shared status snapshot for normal messages and stage heartbeats."""

import json
import re
import tempfile
import threading
import time
from pathlib import Path

TASKS = {"route": "выбор картинок", "summarize": "конспект",
         "filter": "фильтрация", "quiz_explanation": "объяснение квиза",
         "translate": "перевод", "analysis": "анализ"}


class ProgressLog:
    def __init__(self, emit, video, journal_dir=None):
        self.emit = emit
        self.video = video
        self.lock = threading.Lock()
        self.state = {}
        self.requests = 0
        self.journal_dir = journal_dir
        self.lecture_context = None
        self.progress_file = None
        self.thinking_enabled = False
        self.num_gpu = None

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def request_thinking(self):
        """Read browser controls at each request boundary, including retries."""
        if self.progress_file is not None:
            try:
                controls = json.loads((self.progress_file.parent / "analysis-control.json").read_text())
                if isinstance(controls.get("thinking"), bool):
                    self.thinking_enabled = controls["thinking"]
            except (OSError, ValueError, AttributeError):
                pass
        return self.thinking_enabled

    def update(self, **values):
        if "span" in values:
            span = re.fullmatch(r"([\d.]+)–([\d.]+) сек", values["span"])
            values["video_seconds"] = round(float(span[2]) - float(span[1]), 1) if span else None
        with self.lock:
            self.state.update(values)

    def reset_request(self):
        self.update(task="—", request_started=None, request_seconds=0,
                    sent_chars=0, sent_bytes=0, images=0, received=0, thinking=0,
                    limit=None, input_tokens=None, output_tokens=None, request_state="—",
                    request_log=None)

    def begin_request(self, task, model, sent_chars, sent_bytes, images, limit):
        with self.lock:
            self.requests += 1
            self.state.update(task=TASKS.get(task, task), model=model,
                              request_started=time.monotonic(), request_seconds=0,
                              sent_chars=sent_chars, sent_bytes=sent_bytes, images=images,
                              received=0, thinking=0, limit=limit,
                              input_tokens=None, output_tokens=None,
                              request_state="ожидание ответа")

    def __call__(self, message):
        with self.lock:
            state = dict(self.state)
            requests = self.requests
        started = state.get("request_started")
        elapsed = time.monotonic() - started if started is not None else state.get("request_seconds", 0)
        tokens = state.get("output_tokens")
        limit = state.get("limit")
        video_seconds = state.get("video_seconds")
        video_label = f"{video_seconds:g} сек" if video_seconds is not None else "—"
        prefix = (
            f"файл={self.video} | этап={state.get('stage', '—')} | "
            f"блок={state.get('chunk', '—')} [{state.get('span', '—')}] | "
            f"видео={video_label} | "
            f"источники={state.get('sources', '—')} | "
            f"задача={state.get('task', '—')} | запрос={requests} | "
            f"модель={state.get('model', '—')} | "
            f"отправлено={state.get('sent_chars', 0)} симв., "
            f"{state.get('images', 0)} карт., JSON={state.get('sent_bytes', 0)} байт | "
            f"получено={state.get('received', 0)} симв., "
            f"рассуждение={state.get('thinking', 0)} симв. | "
            f"токены вход={state.get('input_tokens') if state.get('input_tokens') is not None else '?'} "
            f"выход={tokens if tokens is not None else '?'}/{limit if limit else '—'} | "
            f"запрос {elapsed:.0f} сек, {state.get('request_state', '—')}"
        )
        self.emit(f"{prefix} | {message}")
        if self.progress_file is not None:
            state.update(message=message, updated=time.time(), requests=requests,
                         request_seconds=round(elapsed, 1), thinking_enabled=self.thinking_enabled)
            with self.lock:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                                 dir=self.progress_file.parent,
                                                 prefix=".progress-", delete=False) as stream:
                    temporary = Path(stream.name)
                    try:
                        json.dump(state, stream, ensure_ascii=False)
                    except BaseException:
                        temporary.unlink(missing_ok=True)
                        raise
                try:
                    temporary.replace(self.progress_file)
                finally:
                    temporary.unlink(missing_ok=True)


def update_status(log, **values):
    if isinstance(log, ProgressLog):
        log.update(**values)
