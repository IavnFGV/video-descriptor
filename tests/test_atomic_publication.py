import json
import os
import threading
import time
from contextlib import contextmanager

import pytest

from video_descriptor import atomic_file, jobs, speech


@contextmanager
def deny_delete(path):
    """Hold a file the way a reader that forbids replacement does."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def test_publish_retries_a_transient_sharing_lock(tmp_path, monkeypatch):
    """A momentary denial must not lose the published artifact."""
    target = tmp_path / 'speech.json'
    target.write_text('{"old": 1}', encoding='utf-8')
    original = atomic_file._swap
    attempts = []

    def swap(source, destination):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError(13, 'sharing violation')
        original(source, destination)

    monkeypatch.setattr(atomic_file, '_swap', swap)
    monkeypatch.setattr(atomic_file.time, 'sleep', lambda _: None)
    atomic_file.write_json(target, {'new': 1})
    assert len(attempts) == 3
    assert json.loads(target.read_text(encoding='utf-8')) == {'new': 1}
    assert not list(tmp_path.glob('.speech.json.*'))


def test_publish_keeps_the_previous_artifact_when_the_lock_persists(tmp_path, monkeypatch):
    """A denied replacement leaves the earlier artifact and no temporary file."""
    target = tmp_path / 'speech.json'
    target.write_text('{"old": 1}', encoding='utf-8')
    monkeypatch.setattr(atomic_file, '_swap',
                        lambda *a: (_ for _ in ()).throw(PermissionError(13, 'locked')))
    monkeypatch.setattr(atomic_file.time, 'sleep', lambda _: None)
    with pytest.raises(PermissionError):
        atomic_file.write_json(target, {'new': 1})
    assert json.loads(target.read_text(encoding='utf-8')) == {'old': 1}
    assert not list(tmp_path.glob('.speech.json.*'))


def test_concurrent_publishers_do_not_share_a_temporary_file(tmp_path):
    """Two processes writing one artifact must not overwrite each other's temporary file."""
    target = tmp_path / 'job.json'
    errors = []

    def publish(value):
        try:
            atomic_file.write_json(target, value)
        except OSError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=publish, args=({'value': index},)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors
    assert json.loads(target.read_text(encoding='utf-8')) in [{'value': index} for index in range(4)]


@pytest.mark.skipif(os.name != 'nt', reason='Windows sharing rules')
def test_our_reader_does_not_block_the_publisher(tmp_path):
    """The reader that polls results must not forbid their replacement."""
    target = tmp_path / 'speech.json'
    target.write_text('{"old": 1}', encoding='utf-8')
    with atomic_file.open_shared(target) as stream:
        assert json.loads(stream.read()) == {'old': 1}
        atomic_file.write_json(target, {'new': 1})
    assert json.loads(target.read_text(encoding='utf-8')) == {'new': 1}


@pytest.mark.skipif(os.name != 'nt', reason='Windows sharing rules')
def test_api_reads_never_block_the_publisher(tmp_path):
    """Polling the API while results are published must not fail either side."""
    target = tmp_path / 'speech.json'
    target.write_text('{"value": 0}', encoding='utf-8')
    errors = []
    stop = threading.Event()

    def publish():
        index = 0
        while not stop.is_set():
            try:
                atomic_file.write_json(target, {'value': index})
            except OSError as exc:
                errors.append(exc)
                return
            index += 1

    thread = threading.Thread(target=publish)
    thread.start()
    try:
        for _ in range(50):
            assert isinstance(jobs.read_json(target, {}), dict)
    finally:
        stop.set()
        thread.join(timeout=30)
    assert not errors


@pytest.mark.skipif(os.name != 'nt', reason='Windows sharing rules')
def test_external_holder_is_waited_out(tmp_path):
    """A holder that forbids deletion is waited out instead of failing the publication."""
    target = tmp_path / 'speech.json'
    target.write_text('{"old": 1}', encoding='utf-8')

    def hold():
        with deny_delete(target):
            time.sleep(.05)

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        atomic_file.write_json(target, {'new': 1})
    finally:
        thread.join(timeout=30)
    assert json.loads(target.read_text(encoding='utf-8')) == {'new': 1}


def test_progress_failure_is_reported_and_never_raises(tmp_path, monkeypatch):
    """A locked progress snapshot is reported without aborting recognition."""
    events = []

    def locked(*args, **kwargs):
        raise PermissionError(13, 'sharing violation')

    monkeypatch.setattr(speech, 'write_json', locked)
    monkeypatch.setattr(speech, 'record', lambda action, **fields: events.append((action, fields)))
    failure = speech.save_progress(tmp_path / 'speech.json', {'status': 'running'}, 'a' * 32)
    assert failure and 'PermissionError' in failure
    assert events[0][0] == 'speech_progress_save_failed'
    assert events[0][1]['reason'] == 'PermissionError'


def recording_job(tmp_path, monkeypatch, transcribe):
    """Prepare a local recognition job with a stubbed device."""
    import wave

    from video_descriptor import speech_devices

    data = tmp_path / 'data'
    data.mkdir(exist_ok=True)
    video = data / 'meeting.wav'
    with wave.open(str(video), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\0\0' * 16000)
    job = speech.enqueue_existing(tmp_path, str(video), 'whisper-local')
    job['device_plan'] = {'requested': 'NPU', 'selected': 'NPU',
                          'engine': {'device': 'NPU', 'model_sha256': 'model', 'version': 1},
                          'runtime': str(tmp_path),
                          'backends': [{'device': 'NPU', 'url': 'http://npu'}]}
    speech.write_json(tmp_path / 'output' / 'jobs' / job['id'] / 'job.json', job)
    monkeypatch.setattr(speech_devices, 'transcribe', transcribe)
    return job


def test_locked_progress_snapshot_does_not_stop_the_result(tmp_path, monkeypatch):
    """Recognition finishes and the result is published even if progress cannot be written."""
    def transcribe(audio, folder, on_chunk, log, plan, job_id, language='auto', on_unresolved=None):
        speech.write_json(folder / 'device-state.json',
                          {'active': 'NPU', 'switches': [], 'engines': {}, 'identity': {}})
        items = [{'start': 0, 'end': 1, 'text': 'Привіт', 'speaker': 'Без розметки'}]
        on_chunk(items, 1)
        return items, 'segment'

    job = recording_job(tmp_path, monkeypatch, transcribe)
    original = speech.write_json
    events = []

    def write(path, value, attempts=None):
        if isinstance(value, dict) and value.get('status') == 'running':
            raise PermissionError(13, 'sharing violation')
        return original(path, value) if attempts is None else original(path, value, attempts)

    monkeypatch.setattr(speech, 'write_json', write)
    monkeypatch.setattr(speech, 'record', lambda action, **fields: events.append((action, fields)))
    speech.run(tmp_path, tmp_path / 'output' / 'jobs' / job['id'], job)
    result = jobs.read_json(tmp_path / 'output' / job['folder'] / 'speech.json')
    assert result['status'] == 'done'
    assert [row['text'] for row in result['segments']] == ['Привіт']
    assert 'speech_progress_save_failed' in [action for action, _ in events]


def test_original_failure_survives_a_locked_result_snapshot(tmp_path, monkeypatch):
    """The reported cause stays the original failure, not the failed snapshot."""
    def transcribe(*args, **kwargs):
        raise RuntimeError('модель недоступна')

    job = recording_job(tmp_path, monkeypatch, transcribe)
    original = speech.write_json
    events = []

    def write(path, value, attempts=None):
        if isinstance(value, dict) and value.get('status') == 'error':
            raise PermissionError(13, 'sharing violation')
        return original(path, value) if attempts is None else original(path, value, attempts)

    monkeypatch.setattr(speech, 'write_json', write)
    monkeypatch.setattr(speech, 'record', lambda action, **fields: events.append((action, fields)))
    with pytest.raises(RuntimeError, match='модель недоступна'):
        speech.run(tmp_path, tmp_path / 'output' / 'jobs' / job['id'], job)
    assert 'speech_result_save_failed' in [action for action, _ in events]
