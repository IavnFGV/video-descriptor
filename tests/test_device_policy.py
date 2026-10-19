import itertools
import json
import wave
from unittest.mock import Mock

import pytest
import requests

from video_descriptor import device_policy, local_backends, speech_devices
from video_descriptor.action_history import record
from video_descriptor.jobs import read_json


@pytest.mark.parametrize('available', list(itertools.product([False, True], repeat=3)))
def test_auto_priority_for_every_hardware_combination(available):
    caps = dict(zip(device_policy.DEVICES, [{'available': v} for v in available], strict=True))
    expected = [d for d, present in zip(device_policy.DEVICES, available, strict=True) if present]
    if expected:
        assert device_policy.select('auto', caps) == expected[0]
    else:
        with pytest.raises(ValueError, match='Нет доступного'):
            device_policy.select('auto', caps)


def test_explicit_device_never_silently_selects_another():
    with pytest.raises(ValueError):
        device_policy.select('GPU', {'CPU': {'available': True}})
    assert device_policy.select('cpu', {d: {'available': True} for d in device_policy.DEVICES}) == 'CPU'


def test_startup_fallback_and_manual_failure(monkeypatch, tmp_path):
    def ensure(backend, runtime):
        if backend['device'] == 'NPU':
            raise local_backends.BackendUnavailable('driver failure')
        return {'device': 'GPU', 'model_sha256': 'model'}
    monkeypatch.setattr(local_backends, 'ensure_backend', ensure)
    backends = {d: {'device': d} for d in device_policy.DEVICES}
    caps = {d: {'available': True} for d in device_policy.DEVICES}
    plan = local_backends.plan('AUTO', caps, backends, tmp_path)
    assert plan['selected'] == 'GPU'
    assert plan['selection_reasons'][0]['device'] == 'NPU'
    with pytest.raises(local_backends.BackendUnavailable):
        local_backends.plan('NPU', caps, backends, tmp_path)


def fixture(tmp_path, monkeypatch, requested='AUTO'):
    audio = tmp_path / 'audio.wav'
    with wave.open(str(audio), 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\x01\0' * (600 * 16000))
    engines = {d: {'device': d, 'model_sha256': 'same-model', 'version': 1} for d in ['NPU', 'GPU', 'CPU']}
    plan = {'requested': requested, 'selected': 'NPU', 'engine': engines['NPU'], 'runtime': str(tmp_path),
            'backends': [{'device': d, 'url': 'http://'+d} for d in engines]}
    monkeypatch.setattr(speech_devices, 'speech_regions', lambda raw: [(0, len(raw) // 2)])
    monkeypatch.setattr(speech_devices, 'ensure_backend', lambda b, r: engines[b['device']])
    return audio, engines, plan


def reply(engine, end=.8):
    return Mock(ok=True, json=lambda: {'engine': engine, 'audio_seconds': 300,
                                      'segments': [{'start': .1, 'end': end, 'text': 'Text'}]})


def test_runtime_fallback_keeps_completed_regions_and_provenance_on_resume(tmp_path, monkeypatch):
    audio, engines, plan = fixture(tmp_path, monkeypatch)
    transport = Mock()
    transport.post.side_effect = [reply(engines['NPU']), requests.ConnectionError('lost'), reply(engines['GPU'])]
    monkeypatch.setattr(speech_devices.requests, 'Session', lambda: transport)
    items, timing = speech_devices.transcribe(audio, tmp_path, Mock(), Mock(), plan, 'job')
    assert [(r['start'], r['end']) for r in items] == [(.1, .8), (300.1, 300.8)]
    assert timing == 'segment'
    state = read_json(tmp_path / 'device-state.json')
    assert state['active'] == 'GPU' and state['switches'][0]['previous_device'] == 'NPU'
    transport.post.side_effect = AssertionError('Completed speech must not be sent again')
    resumed, _ = speech_devices.transcribe(audio, tmp_path, Mock(), Mock(), plan, 'job')
    assert resumed == items
    assert transport.post.call_count == 3
    cached = list(tmp_path.glob('local-*/speech-*/response.json'))
    assert {read_json(p)['engine']['device'] for p in cached} == {'NPU', 'GPU'}


def test_manual_runtime_error_does_not_fall_back(tmp_path, monkeypatch):
    audio, _, plan = fixture(tmp_path, monkeypatch, 'NPU')
    transport = Mock()
    transport.post.side_effect = requests.ConnectionError('lost')
    monkeypatch.setattr(speech_devices.requests, 'Session', lambda: transport)
    with pytest.raises(local_backends.BackendUnavailable):
        speech_devices.transcribe(audio, tmp_path, Mock(), Mock(), plan, 'job')
    assert transport.post.call_count == 1


def test_auto_can_reach_cpu_after_both_accelerators_fail(tmp_path, monkeypatch):
    audio, engines, plan = fixture(tmp_path, monkeypatch)
    transport = Mock()
    transport.post.side_effect = [requests.ConnectionError('NPU lost'), requests.Timeout('GPU lost'),
                                  reply(engines['CPU']), reply(engines['CPU'])]
    monkeypatch.setattr(speech_devices.requests, 'Session', lambda: transport)
    items, _ = speech_devices.transcribe(audio, tmp_path, Mock(), Mock(), plan, 'job')
    state = read_json(tmp_path / 'device-state.json')
    assert len(items) == 2 and state['active'] == 'CPU'
    assert [s['device'] for s in state['switches']] == ['GPU', 'CPU']


def test_pending_compilation_does_not_spawn_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(local_backends, 'engine_info', Mock(side_effect=local_backends.BackendUnavailable()))
    monkeypatch.setattr(local_backends, 'pending_process', lambda state: True)
    spawn = Mock(side_effect=AssertionError('Duplicate worker'))
    monkeypatch.setattr(local_backends.subprocess, 'Popen', spawn)
    with pytest.raises(local_backends.BackendUnavailable, match='предыдущая загрузка'):
        local_backends.ensure_backend({'device': 'CPU'}, tmp_path, timeout=0)
    spawn.assert_not_called()


def test_unclosed_timestamp_is_diagnosed_without_device_fallback(tmp_path, monkeypatch):
    audio, engines, plan = fixture(tmp_path, monkeypatch)
    transport = Mock()
    transport.post.return_value = reply(engines['NPU'], -1)
    monkeypatch.setattr(speech_devices.requests, 'Session', lambda: transport)
    with pytest.raises(ValueError, match='end_ts=-1'):
        speech_devices.transcribe(audio, tmp_path, Mock(), Mock(), plan, 'job')
    assert transport.post.call_count == 1
    assert list(tmp_path.glob('local-*/speech-*/invalid-response.json'))
    assert not list(tmp_path.glob('local-*/speech-*/response.json'))


def test_events_exclude_transcript_tokens_and_arbitrary_payload(tmp_path):
    target = tmp_path / 'events.jsonl'
    record('device_selected', path=target, device='CPU', job_id='job',
           text='private transcript', api_key='secret', request={'messages': ['private']})
    event = json.loads(target.read_text(encoding='utf-8'))
    assert event['device'] == 'CPU'
    assert not {'text', 'api_key', 'request'}.intersection(event)


def test_rejected_request_is_not_misreported_as_timestamps(tmp_path, monkeypatch):
    audio, _, plan = fixture(tmp_path, monkeypatch)
    transport = Mock()
    transport.post.return_value = Mock(ok=False, status_code=400, text='Unsupported language')
    monkeypatch.setattr(speech_devices.requests, 'Session', lambda: transport)
    with pytest.raises(ValueError, match='сервис отклонил аудиофрагмент'):
        speech_devices.transcribe(audio, tmp_path, Mock(), Mock(), plan, 'job')
    assert transport.post.call_count == 1


def test_timestamp_failure_restores_legacy_retry_and_resume_on_same_device(tmp_path, monkeypatch):
    audio, engines, plan = fixture(tmp_path, monkeypatch, 'NPU')
    with wave.open(str(audio), 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\x01\0' * (60 * 16000))
    monkeypatch.setattr(speech_devices, 'speech_regions', lambda raw: [(0, len(raw) // 2)])
    valid = {'engine': engines['NPU'], 'audio_seconds': 30,
             'segments': [{'start': 1, 'end': 29, 'text': 'Speech'}]}
    transport = Mock()
    transport.post.side_effect = [Mock(ok=False, status_code=500, text='NPU returned invalid timestamps'),
                                  Mock(ok=True, json=lambda: valid), Mock(ok=True, json=lambda: valid)]
    monkeypatch.setattr(speech_devices.requests, 'Session', lambda: transport)
    items, _ = speech_devices.transcribe(audio, tmp_path, Mock(), Mock(), plan, 'job')
    assert [(r['start'], r['end']) for r in items] == [(1, 29), (31, 59)]
    assert read_json(tmp_path / 'device-state.json')['switches'] == []
    assert transport.post.call_count == 3
    transport.post.side_effect = AssertionError('Completed retries must be reused')
    resumed, _ = speech_devices.transcribe(audio, tmp_path, Mock(), Mock(), plan, 'job')
    assert resumed == items
    assert transport.post.call_count == 3


def test_vad_rejects_no_speech_without_calling_whisper(tmp_path, monkeypatch):
    audio, _, plan = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(speech_devices, 'speech_regions', lambda raw: [])
    transport = Mock()
    transport.post.side_effect = AssertionError('No speech: Whisper must not be called')
    monkeypatch.setattr(speech_devices.requests, 'Session', lambda: transport)
    checkpoint = Mock()
    items, _ = speech_devices.transcribe(audio, tmp_path, checkpoint, Mock(), plan, 'job')
    assert items == []
    assert checkpoint.call_args.args[1] == 600
    transport.post.assert_not_called()


def test_vad_does_not_trim_model_context(tmp_path, monkeypatch):
    audio, engines, plan = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(speech_devices, 'speech_regions', lambda raw: [(44288, 3936512)])
    transport = Mock()
    transport.post.return_value = reply(engines['NPU'])
    monkeypatch.setattr(speech_devices.requests, 'Session', lambda: transport)
    speech_devices.transcribe(audio, tmp_path, Mock(), Mock(), plan, 'job')
    import io
    for call in transport.post.call_args_list:
        with wave.open(io.BytesIO(call.kwargs['data']), 'rb') as request:
            assert request.getnframes() == 300 * 16000
