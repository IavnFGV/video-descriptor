import wave
from unittest.mock import Mock

import pytest
import requests

from video_descriptor import speech_npu


@pytest.fixture(autouse=True)
def fake_vad(monkeypatch):
    # Protocol tests isolate inference; dedicated cases below supply speech gaps.
    monkeypatch.setattr(speech_npu, 'speech_regions', lambda raw: [(0, len(raw) // 2)])


def wav(path, seconds):
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\0\0' * round(seconds * 16000))
    return path


def test_npu_resume_uses_completed_chunks_and_prefers_real_words(tmp_path, monkeypatch):
    engine = {'model': 'small', 'device': 'NPU'}
    monkeypatch.setattr(speech_npu, 'health', lambda: engine)
    first = {'engine': engine, 'audio_seconds': 300, 'seconds': 10,
             'segments': [{'start': 0, 'end': 20, 'text': 'Segment'}],
             'words': [{'start': 1, 'end': 2, 'text': 'Привет'}]}
    last = {'engine': engine, 'audio_seconds': 1, 'seconds': .1,
            'words': [{'start': .2, 'end': .8, 'text': 'Да'}]}
    post = Mock(side_effect=[Mock(ok=True, json=lambda: first), requests.ConnectionError('interrupted')])
    monkeypatch.setattr(speech_npu.requests, 'post', post)
    audio = wav(tmp_path / 'audio.wav', 301)
    with pytest.raises(requests.ConnectionError):
        speech_npu.transcribe(audio, tmp_path, Mock(), Mock())
    post.side_effect = [Mock(ok=True, json=lambda: last)]
    items, timing = speech_npu.transcribe(audio, tmp_path, Mock(), Mock())
    assert timing == 'word'
    assert [(w['start'], w['text']) for w in items] == [(1, 'Привет'), (300.2, 'Да')]
    assert post.call_count == 3


def test_npu_segment_timing_is_not_fabricated_and_invalid_reply_not_cached(tmp_path, monkeypatch):
    engine = {'model': 'small', 'device': 'NPU'}
    monkeypatch.setattr(speech_npu, 'health', lambda: engine)
    response = {'engine': engine, 'audio_seconds': 1,
                'segments': [{'start': 0, 'end': 1, 'text': 'Два слова'}]}
    monkeypatch.setattr(speech_npu.requests, 'post', Mock(return_value=Mock(ok=True, json=lambda: response)))
    items, timing = speech_npu.transcribe(wav(tmp_path / 'audio.wav', 1), tmp_path, Mock(), Mock())
    assert timing == 'segment' and len(items) == 1
    response['segments'][0]['end'] = 20
    folder = tmp_path / 'invalid'
    folder.mkdir()
    with pytest.raises(ValueError, match='таймкоды'):
        speech_npu.transcribe(tmp_path / 'audio.wav', folder, Mock(), Mock())
    assert not list(folder.glob('*/response.json'))


def test_npu_rejects_english_worker(monkeypatch):
    monkeypatch.setattr(speech_npu.requests, 'get', Mock(return_value=Mock(
        json=lambda: {'protocol': 1, 'device': 'NPU', 'model': 'base.en'})))
    with pytest.raises(ValueError, match='multilingual'):
        speech_npu.health()


def test_npu_split_chunks_remain_cached_on_resume(tmp_path, monkeypatch):
    engine = {'model': 'small', 'device': 'NPU'}
    monkeypatch.setattr(speech_npu, 'health', lambda: engine)
    half = {'engine': engine, 'audio_seconds': 150, 'seconds': 1,
            'segments': [{'start': 0, 'end': 150, 'text': 'Реплика'}]}
    post = Mock(side_effect=[Mock(ok=False, status_code=500, text='NPU returned invalid timestamps'),
                            Mock(ok=True, json=lambda: half), Mock(ok=True, json=lambda: half)])
    monkeypatch.setattr(speech_npu.requests, 'post', post)
    audio = wav(tmp_path / 'audio.wav', 300)
    items, _ = speech_npu.transcribe(audio, tmp_path, Mock(), Mock())
    assert [w['start'] for w in items] == [0, 150]
    assert post.call_count == 3
    post.side_effect = AssertionError('Completed split chunks must not be resent')
    resumed, _ = speech_npu.transcribe(audio, tmp_path, Mock(), Mock())
    assert resumed == items


def test_vad_silence_is_checkpointed_without_npu_request(tmp_path, monkeypatch):
    monkeypatch.setattr(speech_npu, 'health', lambda: {'device': 'NPU'})
    monkeypatch.setattr(speech_npu, 'speech_regions', lambda raw: [])
    post = Mock(side_effect=AssertionError('Do not send silence to NPU'))
    monkeypatch.setattr(speech_npu.requests, 'post', post)
    audio = wav(tmp_path / 'audio.wav', 300)
    callback = Mock()
    assert speech_npu.transcribe(audio, tmp_path, callback, Mock())[0] == []
    assert callback.call_args.args[1] == 300
    monkeypatch.setattr(speech_npu, 'speech_regions', Mock(side_effect=AssertionError('Silence cache lost')))
    speech_npu.transcribe(audio, tmp_path, Mock(), Mock())
    post.assert_not_called()


def test_vad_removed_gaps_keep_original_timestamps(tmp_path, monkeypatch):
    engine = {'device': 'NPU'}
    monkeypatch.setattr(speech_npu, 'health', lambda: engine)
    monkeypatch.setattr(speech_npu, 'speech_regions', lambda raw: [(16000, 32000), (80000, 96000)])
    reply = {'engine': engine, 'audio_seconds': 1, 'seconds': .1,
             'segments': [{'start': .1, 'end': .8, 'text': 'Да'}]}
    post = Mock(return_value=Mock(ok=True, json=lambda: reply))
    monkeypatch.setattr(speech_npu.requests, 'post', post)
    items, _ = speech_npu.transcribe(wav(tmp_path / 'audio.wav', 8), tmp_path, Mock(), Mock())
    assert [(i['start'], i['end']) for i in items] == [(1.1, 1.8), (5.1, 5.8)]
    assert post.call_count == 2
    assert all(len(call.kwargs['data']) == 32000 + 44 for call in post.call_args_list)
