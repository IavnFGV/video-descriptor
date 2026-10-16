import importlib.util
import json
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest

from video_descriptor.cache import reuse_speech
from video_descriptor.frames import extract_scene_frames
from video_descriptor.media import run


@pytest.mark.skipif(not shutil.which("ffmpeg") and not importlib.util.find_spec('imageio_ffmpeg'), reason="FFmpeg required")
def test_ffmpeg_selects_change_and_heartbeat_with_absolute_times(monkeypatch, tmp_path):
    video = tmp_path / "clip.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=160x90:d=3",
         "-f", "lavfi", "-i", "color=white:s=160x90:d=5", "-filter_complex",
         "[0:v][1:v]concat=n=2:v=1:a=0", "-c:v", "libx264", str(video)])
    monkeypatch.setattr("video_descriptor.media.run", lambda command:
                        "text" if command[0] == "tesseract" else run(command))
    sources = extract_scene_frames(video, tmp_path / "frames", 1, 7, "eng", Mock(), max_gap=4)
    assert [source.start for source in sources] == [1, 3, 7]
    assert [source.end for source in sources] == [3, 7, 8]
    assert all((tmp_path / source.image).exists() for source in sources)
    selection = json.loads((tmp_path / "frame-selection.json").read_text())
    assert [frame["reason"] for frame in selection["frames"]] == ["initial", "change", "heartbeat"]


def test_strategy_change_reuses_speech_but_not_frames(tmp_path):
    identity = {"video": "/lecture.mp4", "size": 100, "mtime": 200, "start": 0,
                "duration": None, "whisper": "base.en", "language": "en"}
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "manifest.json").write_text(json.dumps(identity))
    (old / "audio.wav").write_bytes(b"audio")
    (old / "transcript.json").write_text("[]")
    (old / "frames.json").write_text("[]")
    reuse_speech(new, {**identity, "frame_selection": {"strategy": "scene"}}, Mock())
    assert (new / "transcript.json").exists()
    assert (new / "audio.wav").read_bytes() == b"audio"
    assert not (new / "frames.json").exists()


def test_partial_cache_relocates_audio_identity_and_rejects_other_fragment(tmp_path):
    identity = {"video": "/lecture.mp4", "size": 100, "mtime": 200, "start": 60,
                "duration": 120, "whisper": "base.en", "language": "en"}
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "manifest.json").write_text(json.dumps(identity))
    (old / "audio.wav").write_bytes(b"audio")
    state = {"identity": {"audio": str(old / "audio.wav")}, "sources": [],
             "completed_until": 60, "done": False}
    (old / "transcript.partial.json").write_text(json.dumps(state))
    reuse_speech(new, {**identity, "start": 0}, Mock())
    assert not (new / "audio.wav").exists()
    reuse_speech(new, identity, Mock())
    saved = json.loads((new / "transcript.partial.json").read_text())
    assert Path(saved["identity"]["audio"]) == (new / "audio.wav").resolve()
    assert saved["completed_until"] == 60
