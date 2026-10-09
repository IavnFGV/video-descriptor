import json
from unittest.mock import Mock

import pytest

from video_descriptor.notes import chat_json


def response(content, reason):
    result = Mock()
    result.iter_lines.return_value = [json.dumps({
        "done": True, "done_reason": reason, "message": {"content": content},
    }).encode()]
    return result


def test_truncated_response_is_discarded_and_retried_with_same_evidence(monkeypatch):
    first = response('{"notes":', "length")
    second = response('{"notes": []}', "stop")

    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs["json"])
        if len(calls) == 1:
            return first
        first.close.assert_called_once()
        return second

    monkeypatch.setattr("video_descriptor.notes.requests.post", request)
    result = chat_json("prompt", {"sources": ["s1"]}, {}, "model", "http://local",
                       images=["image"], context=8192)
    assert result == '{"notes": []}'
    before, after = calls
    assert before["messages"] == after["messages"]
    assert before["options"]["num_predict"] == 4096
    assert after["options"]["num_predict"] == 8192
    assert after["options"]["num_ctx"] >= 12288
    second.close.assert_called_once()


def test_second_truncation_fails_without_unbounded_retries(monkeypatch):
    responses = [response("partial", "length"), response("still partial", "length")]
    post = Mock(side_effect=responses)
    monkeypatch.setattr("video_descriptor.notes.requests.post", post)
    with pytest.raises(RuntimeError, match="даже после повтора"):
        chat_json("prompt", [], {}, "model", "http://local")
    assert post.call_count == 2
    for item in responses:
        item.close.assert_called_once()
