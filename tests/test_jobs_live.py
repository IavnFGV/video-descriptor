import io
import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from video_descriptor import jobs, live
from video_descriptor.notes import chat_json
from video_descriptor.progress import ProgressLog
from video_descriptor.serve import RangeRequestHandler


def test_upload_is_streamed_queued_and_retry_keeps_same_video(tmp_path, monkeypatch):
    start = Mock()
    monkeypatch.setattr("video_descriptor.serve.start_worker", start)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(RangeRequestHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        response = requests.post(base + "/api/upload", params={"filename": "лекция.mp4", "title": "AWS", "thinking": "true"}, data=b"video content", timeout=5)
        assert response.status_code == 202
        job = response.json()
        assert job["status"] == "queued" and job["thinking"] is True
        assert jobs.video_url(tmp_path, job["video"]).startswith("/data/uploads/")
        assert Path(job["video"]).read_bytes() == b"video content"
        assert requests.get(base + "/api/job", params={"id": job["id"]}, timeout=5).json()["progress"] is None
        file = jobs.jobs_dir(tmp_path) / job["id"] / "job.json"
        job.update(status="error", error="stopped")
        jobs.write_json(file, job)
        retried = requests.post(base + "/api/retry", params={"id": job["id"]}, timeout=5)
        assert retried.status_code == 202
        assert retried.json()["video"] == job["video"]
        assert start.call_count == 2
        assert requests.post(base + "/api/upload?filename=bad.exe", data=b"file", timeout=5).status_code == 400
        assert requests.get(base + "/api/progress?folder=../", timeout=5).status_code == 404
        folder = tmp_path / "output" / "lecture"
        request = folder / "requests" / "one"
        request.mkdir(parents=True)
        original = {"payload": {"messages": [{"role": "user", "content": "OCR", "images": ["actual-image"]}]}}
        jobs.write_json(request / "request.json", original)
        response = requests.get(base + "/api/request?folder=lecture&request=one", timeout=5)
        assert response.json() == original
        assert requests.get(base + "/api/request?folder=lecture&request=..", timeout=5).status_code == 404
        jobs.write_json(folder / "manifest.json", {"video": "lecture.mp4"})
        toggle = requests.post(base + "/api/thinking?folder=lecture", json={"thinking": False}, timeout=5)
        assert toggle.status_code == 200
        assert jobs.read_json(folder / "analysis-control.json") == {"thinking": False}
        assert requests.post(base + "/api/thinking?folder=lecture", json={"thinking": "false"}, timeout=5).status_code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_interrupted_upload_is_not_queued(tmp_path):
    with pytest.raises(ValueError, match="оборвалась"):
        jobs.enqueue(tmp_path, io.BytesIO(b"short"), 100, "lecture.mp4")
    assert not list(tmp_path.glob("output/jobs/*/job.json"))
    assert not list(tmp_path.glob("data/uploads/*/lecture.mp4"))


def test_snapshot_reads_actual_checkpoints_and_stream_without_accepting_draft(tmp_path, monkeypatch):
    folder = tmp_path / "output" / "lecture"
    folder.mkdir(parents=True)
    jobs.write_json(folder / "manifest.json", {"video": str(tmp_path / "lecture.mp4"), "processed_duration": 100})
    jobs.write_json(folder / "transcript.partial.json", {"sources": [{"id": "s1", "start": 0, "end": 7, "text": "hello"}]})
    jobs.write_json(folder / "progress.json", {"stage": "[2/5] Аудио", "message": "saved"})
    request = folder / "requests" / "one"
    request.mkdir(parents=True)
    (request / "events.jsonl").write_text('{"message":{"thinking":"reason","content":"partial"}}\nnot complete', encoding="utf-8")
    monkeypatch.setattr(live, "active_video", lambda video: True)
    result = live.snapshot(tmp_path, folder)
    assert result["position"] == 7
    assert result["speech_count"] == 1
    # A previous language-model request must not leak into the speech stage.
    assert result["thinking"] == ""
    assert result["response"] == ""
    assert result["notes"] == []
    assert result["running"] and not result["done"]
    jobs.write_json(request / "request.json", {"payload": {"messages": []}})
    assert live.snapshot(tmp_path, folder)["request_url"] is None
    jobs.write_json(folder / "progress.json", {"stage": "[4/5] Конспект", "task": "конспект"})
    assert live.snapshot(tmp_path, folder)["request_url"] == "/api/request?folder=lecture&request=one"
    jobs.write_json(folder / "transcript.json", [
        {"id": "s1", "start": 0, "end": 7, "text": "first"},
        {"id": "s2", "start": 20, "end": 30, "text": "current"},
    ])
    jobs.write_json(folder / "progress.json", {"stage": "[4/5] Конспект", "span": "20–40 сек"})
    current = live.snapshot(tmp_path, folder)
    assert current["speech_count"] == 2
    assert [s["id"] for s in current["speech"]] == ["s2"]


def test_worker_continues_next_job_after_a_failure(tmp_path, monkeypatch):
    first = jobs.enqueue(tmp_path, io.BytesIO(b"a"), 1, "a.mp4")
    second = jobs.enqueue(tmp_path, io.BytesIO(b"b"), 1, "b.mp4")
    # This test checks continuation after failure, not the OS wall clock's
    # resolution (two Windows time.time() calls can produce identical values).
    for created, job in enumerate((first, second), 1):
        job['created'] = created
        jobs.write_json(jobs.jobs_dir(tmp_path) / job['id'] / 'job.json', job)
    order = []
    def process(root, folder, job):
        order.append(job["id"])
        job["status"] = "error" if job["id"] == first["id"] else "done"
        jobs.write_json(folder / "job.json", job)
    monkeypatch.setattr(jobs, "pipeline_busy", lambda: False)
    monkeypatch.setattr(jobs, "run_job", process)
    jobs.worker(tmp_path, stay_alive=False)
    assert order == [first["id"], second["id"]]


def test_thinking_is_opt_in_and_snapshots_are_written(tmp_path, monkeypatch):
    log = ProgressLog(lambda message: None, "lecture")
    log.progress_file = tmp_path / "progress.json"
    response = Mock()
    response.iter_lines.return_value = [b'{"done":true,"message":{"content":"{}","thinking":"reason"}}']
    post = Mock(return_value=response)
    monkeypatch.setattr("video_descriptor.notes.requests.post", post)
    chat_json("prompt", [], {}, "model", "http://local", log)
    assert post.call_args.kwargs["json"]["think"] is False
    log.thinking_enabled = True
    chat_json("prompt", [], {}, "model", "http://local", log)
    assert post.call_args.kwargs["json"]["think"] is True
    state = json.loads(log.progress_file.read_text())
    assert state["thinking_enabled"] is True
    assert state["received"] == 2 and state["thinking"] == 6
    # Browser changes affect the next actual payload, without changing the CLI default.
    jobs.write_json(tmp_path / "analysis-control.json", {"thinking": False})
    chat_json("prompt", [], {}, "model", "http://local", log)
    assert post.call_args.kwargs["json"]["think"] is False
    jobs.write_json(tmp_path / "analysis-control.json", {"thinking": True})
    chat_json("prompt", [], {}, "model", "http://local", log)
    assert post.call_args.kwargs["json"]["think"] is True


def test_inactive_workspace_shows_entire_transcript(tmp_path, monkeypatch):
    folder = tmp_path / "output" / "lecture"
    folder.mkdir(parents=True)
    jobs.write_json(folder / "manifest.json", {"video": str(tmp_path / "lecture.mp4"),
                                              "processed_duration": 200})
    transcript = [{"id": f"s{i}", "start": i, "end": i + 1, "text": f"Reply {i}"}
                  for i in range(100)]
    jobs.write_json(folder / "transcript.json", transcript)
    jobs.write_json(folder / "progress.json", {"stage": "[4/5] Конспект", "span": "90–100 сек"})
    monkeypatch.setattr(live, "active_video", lambda video: False)
    result = live.snapshot(tmp_path, folder)
    assert len(result["speech"]) == 100
    assert result["speech"][0]["id"] == "s0"
    assert result["speech_editor_url"] == "/create?folder=lecture"


def test_interrupted_notes_can_be_deleted_without_ready_report(tmp_path, monkeypatch):
    from video_descriptor.versions import delete_notes

    folder = tmp_path / 'output' / 'draft'
    folder.mkdir(parents=True)
    jobs.write_json(folder / 'manifest.json', {'video': str(tmp_path / 'video.mp4')})
    jobs.write_json(folder / 'transcript.json', [{'id': 's1', 'start': 0, 'end': 1, 'text': 'Keep'}])
    jobs.write_json(folder / 'notes-live.json', {'notes': [], 'sections': []})
    jobs.write_json(folder / 'notes-cache-0001.json', {'notes': [], 'sections': []})
    jobs.write_json(folder / 'chunk-plan-cache.json', {})
    monkeypatch.setattr(live, 'active_video', lambda video: False)
    monkeypatch.setattr('video_descriptor.versions.active_video', lambda video: False)
    before = live.snapshot(tmp_path, folder)
    assert before['has_notes'] and not before['report_variants']
    assert not before['notes_deleted']
    delete_notes(tmp_path, 'draft')
    after = live.snapshot(tmp_path, folder)
    assert not after['has_notes']
    assert after['notes_deleted'] and after['has_ready_transcript']
    assert not after['notes'] and not after['sections']
    assert after['speech'][0]['text'] == 'Keep'
