import hashlib
import json

from video_descriptor.cache import cache_digest


def test_equivalent_cli_numbers_reuse_original_cache_key():
    original = {"start": 0, "duration": None, "interval": 15, "video": "lecture.mp4"}
    batch = {**original, "start": 0.0, "interval": 15.0}
    legacy = hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest()[:10]
    assert cache_digest(original) == cache_digest(batch) == legacy
    assert cache_digest({**batch, "interval": 15.5}) != legacy


def test_nested_scene_settings_are_normalized_without_rounding():
    first = {"frame_selection": {"scan_interval": 1, "max_gap": 60, "threshold": 0.01}}
    second = {"frame_selection": {"scan_interval": 1.0, "max_gap": 60.0, "threshold": 0.01}}
    assert cache_digest(first) == cache_digest(second)
    second["frame_selection"]["threshold"] = 0.02
    assert cache_digest(first) != cache_digest(second)
