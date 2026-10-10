import json
from unittest.mock import Mock

from video_descriptor.notes import chat_json
from video_descriptor.progress import ProgressLog


def test_heartbeat_sees_current_stream_and_final_token_counts(monkeypatch):
    messages = []
    log = ProgressLog(messages.append, "lecture.mp4")
    log.update(stage="4/5", chunk="5/18", span="720–900 сек", sources="речь 20, кадры 12")

    def events():
        yield json.dumps({"message": {"thinking": "think", "content": ""}}).encode()
        # The stream can be quiet; the independent stage heartbeat sees its snapshot.
        log("периодическая проверка")
        assert "рассуждение=5 симв." in messages[-1]
        assert "получено=0 симв." in messages[-1]
        assert "выход=?/4096" in messages[-1]
        yield json.dumps({"message": {"content": "{}"}, "done": True,
                          "prompt_eval_count": 123, "eval_count": 8}).encode()

    response = Mock()
    response.iter_lines.side_effect = events
    monkeypatch.setattr("video_descriptor.notes.requests.post", Mock(return_value=response))
    assert chat_json("hello", [], {}, "local-model", "http://local", log,
                     images=["base64"]) == "{}"
    for message in messages:
        assert "файл=lecture.mp4" in message
        assert "блок=5/18 [720–900 сек]" in message
        assert "видео=180 сек" in message
        assert "отправлено=7 симв., 1 карт." in message
        assert "запрос=1" in message
    assert "токены вход=123 выход=8/4096" in messages[-1]
    assert "получено=2 симв." in messages[-1]
    assert "готово" in messages[-1]
    log.reset_request()
    log.update(chunk="6/18", request_state="из кэша")
    log("следующий блок")
    assert "получено=0 симв." in messages[-1]
    assert "отправлено=0 симв., 0 карт." in messages[-1]
    log.update(span="—")
    log("другой этап")
    assert "видео=—" in messages[-1]


def test_connection_failure_clears_waiting_state(monkeypatch):
    import pytest
    import requests

    messages = []
    log = ProgressLog(messages.append, "lecture.mp4")
    monkeypatch.setattr("video_descriptor.notes.requests.post",
                        Mock(side_effect=requests.ConnectionError("offline")))
    with pytest.raises(requests.ConnectionError):
        chat_json("hello", [], {}, "model", "http://local", log)
    log("ошибка")
    assert "ошибка соединения" in messages[-1]
    assert log.state["request_started"] is None


def test_cpu_override_is_sent_without_affecting_default(monkeypatch):
    response = Mock()
    response.iter_lines.return_value = [b'{"done":true,"message":{"content":"{}"}}']
    post = Mock(return_value=response)
    monkeypatch.setattr("video_descriptor.notes.requests.post", post)
    log = ProgressLog(lambda message: None, "lecture")
    chat_json("prompt", [], {}, "model", "http://local", log)
    assert "num_gpu" not in post.call_args.kwargs["json"]["options"]
    log.num_gpu = 0
    chat_json("prompt", [], {}, "model", "http://local", log)
    assert post.call_args.kwargs["json"]["options"]["num_gpu"] == 0
