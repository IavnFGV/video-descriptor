import json
import threading
import wave
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from scripts.whisper_npu_server import make_handler
from video_descriptor.media import transcribe


@pytest.fixture
def worker(monkeypatch):
    pipeline = Mock()
    info = {"protocol": 1, "device": "NPU", "model": "base.en", "pipeline": "static",
            "num_beams": 1, "model_sha256": "test-model", "openvino": "test", "genai": "test"}
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(pipeline, info))
    pipeline.server_port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("WHISPER_BACKEND", "openvino-http")
    monkeypatch.setenv("WHISPER_HTTP_URL", f"http://127.0.0.1:{server.server_port}")
    yield pipeline
    server.shutdown()
    server.server_close()
    thread.join()


def audio_file(tmp_path, seconds):
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(bytes(round(seconds * 32000)))
    return path


def result(text, end):
    return SimpleNamespace(chunks=[SimpleNamespace(start_ts=0, end_ts=end, text=text)])


def test_remote_resume_preserves_finished_chunks_and_absolute_timestamps(worker, tmp_path):
    worker.generate.side_effect = [result("First", 299.8), RuntimeError("interrupted")]
    audio = audio_file(tmp_path, 301)
    with pytest.raises(RuntimeError, match="interrupted"):
        transcribe(audio, 90, 301, "base.en", "en", Mock())
    state = json.loads((tmp_path / "transcript.partial.json").read_text())
    assert state["completed_until"] == 300
    assert not state["done"]
    worker.generate.side_effect = [result("Last", .9)]
    sources = transcribe(audio, 90, 301, "base.en", "en", Mock())
    assert [(s.id, s.start, s.end, s.text) for s in sources] == [
        ("s00001", 90, 389.8, "First"), ("s00002", 390, 390.9, "Last")]
    assert len(worker.generate.call_args.args[0]) == 16000
    assert worker.generate.call_args.kwargs == {"num_beams": 1, "return_timestamps": True}
    state = json.loads((tmp_path / "transcript.partial.json").read_text())
    assert state["done"]
    assert transcribe(audio, 90, 301, "base.en", "en", Mock()) == sources
    assert worker.generate.call_count == 3


def test_bad_remote_timestamps_do_not_create_completed_cache(worker, tmp_path):
    worker.generate.return_value = result("Broken", 330)
    with pytest.raises(RuntimeError, match="invalid timestamps"):
        transcribe(audio_file(tmp_path, 300), 0, 300, "base.en", "en", Mock())
    assert not (tmp_path / "transcript.partial.json").exists()


def test_language_mismatch_is_rejected_before_inference(worker, tmp_path):
    with pytest.raises(ValueError, match="английскую"):
        transcribe(audio_file(tmp_path, 1), 0, 1, "base.en", "ru", Mock())
    worker.generate.assert_not_called()


def test_invalid_timestamp_block_is_split_without_losing_audio(worker, tmp_path):
    worker.generate.side_effect = [result("Broken", 330), result("First half", 150),
                                   result("Second half", 150)]
    sources = transcribe(audio_file(tmp_path, 300), 10, 300, "base.en", "en", Mock())
    assert [(s.start, s.end, s.text) for s in sources] == [
        (10, 160, "First half"), (160, 310, "Second half")]
    assert [len(call.args[0]) / 16000 for call in worker.generate.call_args_list] == [300, 150, 150]
    state = json.loads((tmp_path / "transcript.partial.json").read_text())
    assert state["done"] and state["completed_until"] == 300


def test_worker_reports_invalid_timestamps_with_machine_readable_body(worker, tmp_path):
    """The worker names the failure so the client can recover instead of guessing."""
    worker.generate.return_value = result("Broken", -1)
    response = requests.post(f"http://127.0.0.1:{worker.server_port}/transcribe",
                             data=audio_file(tmp_path, 10).read_bytes(),
                             headers={"Content-Type": "audio/wav", "X-Whisper-Model": "base.en",
                                      "X-Language": "en"}, timeout=30)
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "invalid_timestamps"
    assert body["invalid"] == {"start": 0.0, "end": -1.0}
    assert "Broken" not in response.text
