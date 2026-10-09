import json
import wave
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from video_descriptor.media import transcribe


def audio_file(path):
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(np.zeros(100 * 16000, dtype="<i2").tobytes())
    return path


def segment(start, end, text):
    return SimpleNamespace(start=start, end=end, text=text)


def test_resume_after_failure_redecodes_tail_without_duplicate_ids(monkeypatch, tmp_path):
    audio = audio_file(tmp_path / "audio.wav")
    def interrupted():
        yield segment(0, 40, "first")
        yield segment(40, 80, "second")
        raise RuntimeError("simulated crash")
    first_model = Mock()
    first_model.transcribe.return_value = (interrupted(), SimpleNamespace(language="en"))
    factory = Mock(return_value=first_model)
    monkeypatch.setattr("faster_whisper.WhisperModel", factory)
    with pytest.raises(RuntimeError, match="simulated crash"):
        transcribe(audio, 600, 100, "base.en", "en", Mock())
    partial = tmp_path / "transcript.partial.json"
    state = json.loads(partial.read_text())
    assert state["completed_until"] == 80
    assert len(state["sources"]) == 2
    assert not state["done"]
    assert not (tmp_path / "transcript.json").exists()
    second_model = Mock()
    second_model.transcribe.return_value = (
        iter([segment(0, 40, "second resumed"), segment(40, 60, "third")]),
        SimpleNamespace(language="en"),
    )
    factory.return_value = second_model
    sources = transcribe(audio, 600, 100, "base.en", "en", Mock())
    assert [source.text for source in sources] == ["first", "second resumed", "third"]
    assert [source.id for source in sources] == ["s00001", "s00002", "s00003"]
    assert [(source.start, source.end) for source in sources] == [(600, 640), (640, 680), (680, 700)]
    tail = second_model.transcribe.call_args.args[0]
    assert isinstance(tail, np.ndarray)
    assert len(tail) == 60 * 16000
    assert json.loads(partial.read_text())["done"]
    factory.reset_mock()
    assert transcribe(audio, 600, 100, "base.en", "en", Mock()) == sources
    factory.assert_not_called()


def test_changed_whisper_model_cannot_reuse_partial_result(monkeypatch, tmp_path):
    audio = audio_file(tmp_path / "audio.wav")
    model = Mock()
    model.transcribe.return_value = (iter([segment(0, 1, "base")]), SimpleNamespace(language="en"))
    monkeypatch.setattr("faster_whisper.WhisperModel", Mock(return_value=model))
    transcribe(audio, 0, 100, "base.en", "en", Mock())
    model.transcribe.return_value = (iter([segment(0, 1, "small")]), SimpleNamespace(language="en"))
    result = transcribe(audio, 0, 100, "small.en", "en", Mock())
    assert result[0].text == "small"
    assert model.transcribe.call_args.args[0] == str(audio)
