"""Adaptive recovery for unusable model timestamps in the device transcription path."""
import array
import io
import itertools
import json
import wave
from unittest.mock import Mock

import pytest
import requests

from video_descriptor import local_backends, speech_devices
from video_descriptor.speech_recovery import MIN_INTERVAL_SECONDS, split_interval

QUIET = 1
LOUD = 16384


def wav(path, seconds, loud=()):
    """Audio where the listed second ranges carry a loud marker the fake worker detects."""
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        frames = bytearray()
        for second in range(seconds):
            sample = LOUD if second in loud else QUIET
            frames += sample.to_bytes(2, 'little', signed=True) * 16000
        stream.writeframes(bytes(frames))
    return path


def plan_for(tmp_path, devices, requested='AUTO'):
    return {'requested': requested, 'selected': 'NPU', 'engine': devices['NPU'], 'runtime': str(tmp_path),
            'backends': [{'device': device, 'url': f'http://{device}'} for device in devices]}


def devices():
    return {device: {'device': device, 'model_sha256': 'same-model', 'version': 1}
            for device in ('NPU', 'GPU', 'CPU')}


def payload_samples(payload):
    """The signed samples of the WAV the worker received."""
    with wave.open(io.BytesIO(payload), 'rb') as stream:
        raw = stream.readframes(stream.getnframes())
    return array.array('h', raw)


def payload_seconds(payload):
    with wave.open(io.BytesIO(payload), 'rb') as stream:
        return stream.getnframes() / 16000


def loud_window(payload):
    """True when the sent WAV carries the marker of audio the model cannot timestamp."""
    return LOUD in payload_samples(payload)


def worker(engine, seconds):
    """A successful worker answer for a window of the given length."""
    return Mock(ok=True, json=lambda: {'engine': engine, 'audio_seconds': seconds,
                                      'segments': [{'start': .1, 'end': max(.2, seconds - .1), 'text': 'Text'}]})


def rejects_timestamps():
    """A worker answer that reports unusable model timestamps."""
    return Mock(ok=False, status_code=500,
                 text=json.dumps({'error': 'NPU returned invalid timestamps',
                                  'code': 'invalid_timestamps',
                                  'invalid': {'start': .0, 'end': -1.0}}))


def fake_worker(plan, loud=()):
    """A worker that rejects exactly the windows overlapping the marked audio."""
    def answer(url, **kwargs):
        if loud and loud_window(kwargs['data']):
            return rejects_timestamps()
        return worker(plan['engine'], payload_seconds(kwargs['data']))
    return answer


def fixture(tmp_path, monkeypatch, seconds=600, loud=(), requested='AUTO'):
    audio = wav(tmp_path / 'audio.wav', seconds, loud)
    plan = plan_for(tmp_path, devices(), requested)
    monkeypatch.setattr(speech_devices, 'speech_regions', lambda raw: [(0, len(raw) // 2)])
    monkeypatch.setattr(speech_devices, 'ensure_backend', lambda backend, runtime: plan['engine'])
    return audio, plan


def install(monkeypatch, transport):
    monkeypatch.setattr(speech_devices.requests, 'Session', lambda: transport)


def run(audio, tmp_path, plan, transport, unresolved=None):
    return speech_devices.transcribe(audio, tmp_path, Mock(), Mock(), plan, 'job',
                                     on_unresolved=unresolved.append if unresolved is not None else None)


def test_worker_reported_invalid_timestamps_split_until_five_seconds(tmp_path, monkeypatch):
    """A window the worker rejects is halved until a five second leaf fails and stays unresolved."""
    audio, plan = fixture(tmp_path, monkeypatch, seconds=120, loud=range(17, 20))
    transport = Mock()
    transport.post.side_effect = fake_worker(plan, loud=True)
    install(monkeypatch, transport)
    unresolved = []

    items, timing = run(audio, tmp_path, plan, transport, unresolved)

    assert timing == 'segment'
    assert len(unresolved) == 1
    entry = unresolved[0]
    assert entry['status'] == 'unresolved'
    assert entry['reason'] == 'invalid_timestamps'
    assert entry['end'] - entry['start'] == MIN_INTERVAL_SECONDS
    assert 15 <= entry['start'] <= 20
    assert items, 'the rest of the recording is still transcribed'


def test_unresolved_interval_carries_absolute_audio_boundaries(tmp_path, monkeypatch):
    """The unresolved range names the exact audio it covers in absolute recording time."""
    audio, plan = fixture(tmp_path, monkeypatch, seconds=600, loud=range(317, 320))
    transport = Mock()
    transport.post.side_effect = fake_worker(plan, loud=True)
    install(monkeypatch, transport)
    unresolved = []

    run(audio, tmp_path, plan, transport, unresolved)

    assert len(unresolved) == 1
    entry = unresolved[0]
    assert entry['start'] == 315.0
    assert entry['end'] == 320.0
    assert entry['id'] == 'u-0005040000-0005120000'


def test_failed_interval_does_not_stop_the_following_audio(tmp_path, monkeypatch):
    """Only the rejected window is lost; the rest of the recording is still transcribed."""
    audio, plan = fixture(tmp_path, monkeypatch, seconds=120, loud=range(17, 20))
    transport = Mock()
    transport.post.side_effect = fake_worker(plan, loud=True)
    install(monkeypatch, transport)
    unresolved = []

    items, _ = run(audio, tmp_path, plan, transport, unresolved)

    assert len(unresolved) == 1
    assert items
    assert max(row['end'] for row in items) > 20


def test_shrinking_recovers_neighbouring_windows_with_absolute_offsets(tmp_path, monkeypatch):
    """After a rejected window, the sibling halves are transcribed with true absolute offsets."""
    audio, plan = fixture(tmp_path, monkeypatch, seconds=120, loud=range(17, 20))
    transport = Mock()
    transport.post.side_effect = fake_worker(plan, loud=True)
    install(monkeypatch, transport)
    unresolved = []

    items, _ = run(audio, tmp_path, plan, transport, unresolved)

    assert len(unresolved) == 1
    starts = [row['start'] for row in items]
    assert starts == sorted(starts)
    assert all(0 <= row['start'] <= 120 for row in items)


def test_client_side_end_timestamp_minus_one_is_unresolved(tmp_path, monkeypatch):
    """A response carrying end_ts=-1 is treated as unusable, never as a finished row."""
    audio, plan = fixture(tmp_path, monkeypatch, seconds=120)
    transport = Mock()

    def answer(url, **kwargs):
        return Mock(ok=True, json=lambda: {'engine': plan['engine'], 'audio_seconds': payload_seconds(kwargs['data']),
                                           'segments': [{'start': .1, 'end': -1, 'text': 'Text'}]})

    transport.post.side_effect = answer
    install(monkeypatch, transport)
    unresolved = []

    items, _ = run(audio, tmp_path, plan, transport, unresolved)

    assert items == []
    assert unresolved
    entry = unresolved[0]
    assert entry['reason'] == 'invalid_timestamps'
    detail = entry.get('detail') or {}
    assert detail.get('end') == -1


def test_multiple_independent_failures_are_reported_separately(tmp_path, monkeypatch):
    """Two rejected windows produce two distinct unresolved ranges."""
    audio, plan = fixture(tmp_path, monkeypatch, seconds=120, loud=[*range(17, 20), *range(60, 63)])
    transport = Mock()
    transport.post.side_effect = fake_worker(plan, loud=True)
    install(monkeypatch, transport)
    unresolved = []

    run(audio, tmp_path, plan, transport, unresolved)

    assert len(unresolved) == 2
    starts = [entry['start'] for entry in unresolved]
    assert starts == sorted(starts)
    assert len({entry['id'] for entry in unresolved}) == 2


def test_recovery_never_repeats_a_segment(tmp_path, monkeypatch):
    """Recovered windows never produce duplicated or overlapping rows."""
    audio, plan = fixture(tmp_path, monkeypatch, seconds=120, loud=range(17, 20))
    transport = Mock()
    transport.post.side_effect = fake_worker(plan, loud=True)
    install(monkeypatch, transport)
    unresolved = []

    items, _ = run(audio, tmp_path, plan, transport, unresolved)

    for previous, current in itertools.pairwise(items):
        assert current['start'] >= previous['end'] - 1e-6


def test_infrastructure_failure_is_not_treated_as_skippable_audio(tmp_path, monkeypatch):
    """A worker outage stops the job instead of silently dropping the audio."""
    audio, plan = fixture(tmp_path, monkeypatch, seconds=120, requested='NPU')
    transport = Mock()
    transport.post.side_effect = requests.ConnectionError('lost')
    install(monkeypatch, transport)
    unresolved = []

    with pytest.raises(local_backends.BackendUnavailable) as excinfo:
        run(audio, tmp_path, plan, transport, unresolved)

    assert 'end_ts' not in str(excinfo.value)
    assert unresolved == []


def test_worker_crash_is_not_treated_as_skippable_audio(tmp_path, monkeypatch):
    """A worker error without timestamp diagnostics aborts instead of skipping the audio."""
    audio, plan = fixture(tmp_path, monkeypatch, seconds=120, requested='NPU')
    transport = Mock()
    transport.post.return_value = Mock(ok=False, status_code=500, text='model crashed')
    install(monkeypatch, transport)
    unresolved = []

    with pytest.raises(local_backends.BackendUnavailable):
        run(audio, tmp_path, plan, transport, unresolved)

    assert unresolved == []


def test_restart_reuses_cached_windows_and_keeps_failed_ranges(tmp_path, monkeypatch):
    """A restart reuses finished windows and reports the same failed ranges."""
    audio, plan = fixture(tmp_path, monkeypatch, seconds=120, loud=range(17, 20))
    transport = Mock()
    transport.post.side_effect = fake_worker(plan, loud=True)
    install(monkeypatch, transport)
    unresolved = []

    run(audio, tmp_path, plan, transport, unresolved)
    first_calls = transport.post.call_count
    first_ids = [entry['id'] for entry in unresolved]

    def refuse(url, **kwargs):
        raise AssertionError('A restart must not resend finished windows')

    transport.post.side_effect = refuse
    resumed = []
    run(audio, tmp_path, plan, transport, resumed)

    assert first_calls > 0
    assert [entry['id'] for entry in resumed] == first_ids


def test_split_keeps_both_halves_above_the_minimum_interval():
    """Every produced split leaves two halves that can still be transcribed."""
    start, end = 0, 300 * 16000
    middle = split_interval(start, end)
    assert middle is not None
    assert middle - start >= MIN_INTERVAL_SECONDS * 16000
    assert end - middle >= MIN_INTERVAL_SECONDS * 16000


def test_split_refuses_intervals_below_the_minimum():
    """An interval that cannot be halved any further is reported as unsplittable."""
    assert split_interval(0, MIN_INTERVAL_SECONDS * 16000) is None
    assert split_interval(0, MIN_INTERVAL_SECONDS * 16000 - 1) is None


def test_recovery_is_written_to_the_shared_action_journal(tmp_path, monkeypatch):
    """Recovery and unresolved intervals appear in the common journal without transcript text."""
    monkeypatch.setenv('VIDEO_DESCRIPTOR_EVENTS', str(tmp_path / 'events.jsonl'))
    audio, plan = fixture(tmp_path, monkeypatch, seconds=120, loud=range(17, 20))
    transport = Mock()
    transport.post.side_effect = fake_worker(plan, loud=True)
    install(monkeypatch, transport)
    unresolved = []

    run(audio, tmp_path, plan, transport, unresolved)

    events = [json.loads(line) for line in (tmp_path / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
    actions = [event['action'] for event in events]
    assert 'speech_timestamps_recovery_started' in actions
    assert 'speech_timestamps_recovery_finished' in actions
    assert 'speech_timestamps_unresolved' in actions
    unresolved_event = next(event for event in events if event['action'] == 'speech_timestamps_unresolved')
    assert unresolved_event['stage'] == 'speech'
    assert unresolved_event['reason'] == 'invalid_timestamps'
    assert unresolved_event['status'] == 'error'
    assert 'Text' not in json.dumps(events, ensure_ascii=False)

