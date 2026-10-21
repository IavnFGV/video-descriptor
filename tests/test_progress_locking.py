import ctypes
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from video_descriptor import construction, gemini, progress
from video_descriptor.progress import ProgressLog


def logger(tmp_path):
    messages = []
    log = ProgressLog(messages.append, 'record', tmp_path / 'requests')
    log.progress_file = tmp_path / 'progress.json'
    log('initial')
    return log, messages


def test_transient_replace_failure_retries_without_losing_snapshot(tmp_path, monkeypatch):
    log, _ = logger(tmp_path)
    original = Path.replace
    attempts = []

    def replace(path, target):
        if Path(target) == log.progress_file:
            attempts.append(1)
            if len(attempts) < 3:
                assert json.loads(log.progress_file.read_text())['message'] == 'initial'
                raise PermissionError(13, 'sharing violation')
        return original(path, target)

    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr(progress.time, 'sleep', lambda _: None)
    log('latest')
    assert len(attempts) == 3
    assert json.loads(log.progress_file.read_text())['message'] == 'latest'
    assert not log.progress_error and not list(tmp_path.glob('.progress-*'))


def test_persistent_lock_is_nonfatal_warns_once_and_recovers(tmp_path, monkeypatch):
    log, messages = logger(tmp_path)
    original = Path.replace
    monkeypatch.setattr(Path, 'replace', lambda *a: (_ for _ in ()).throw(PermissionError(13, 'locked')))
    monkeypatch.setattr(progress.time, 'sleep', lambda _: None)
    log('blocked one')
    log('blocked two')
    assert log.progress_error
    assert json.loads(log.progress_file.read_text())['message'] == 'initial'
    assert sum('Индикатор прогресса' in m for m in messages) == 1
    assert not list(tmp_path.glob('.progress-*'))
    monkeypatch.setattr(Path, 'replace', original)
    log('recovered')
    assert not log.progress_error
    assert json.loads(log.progress_file.read_text())['message'] == 'recovered'


def test_serialization_errors_are_not_swallowed_and_temp_is_cleaned(tmp_path):
    log, _ = logger(tmp_path)
    log.update(unserializable=object())
    with pytest.raises(TypeError):
        log('invalid state')
    assert json.loads(log.progress_file.read_text())['message'] == 'initial'
    assert not list(tmp_path.glob('.progress-*'))


def test_gemini_generation_continues_despite_locked_progress(tmp_path, monkeypatch):
    log, _ = logger(tmp_path)
    original = Path.replace
    monkeypatch.setattr(Path, 'replace', lambda path, target: (_ for _ in ()).throw(PermissionError(13, 'locked')) if Path(target) == log.progress_file else original(path, target))
    monkeypatch.setattr(progress.time, 'sleep', lambda _: None)
    monkeypatch.setattr(construction, 'credentials', lambda root: {'api_key': 'private', 'billing_mode': 'paid'})
    generated = []

    def call(method, url, key, **kw):
        if method == 'GET':
            return {'inputTokenLimit': 65536, 'outputTokenLimit': 4096}
        if url.endswith(':countTokens'):
            return {'totalTokens': 1000}
        generated.append(1)
        return {'candidates': [{'content': {'parts': [{'text': 'Completed notes'}]}, 'finishReason': 'STOP'}]}

    monkeypatch.setattr(gemini, 'call', call)
    answer = construction.generate(tmp_path, construction.validate({'provider': 'gemini', 'model': 'gemini-test'}), 'Transcript', log)
    assert answer == 'Completed notes' and generated == [1]
    assert json.loads(log.progress_file.read_text())['message'] == 'initial'


@contextmanager
def deny_delete(path):
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
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


@pytest.mark.skipif(os.name != 'nt', reason='Real Windows sharing lock')
def test_real_windows_reader_lock_does_not_abort_and_next_write_recovers(tmp_path):
    log, _ = logger(tmp_path)
    with deny_delete(log.progress_file):
        log('locked')
        assert log.progress_error
        assert json.loads(log.progress_file.read_text())['message'] == 'initial'
    log('unlocked')
    assert not log.progress_error
    assert json.loads(log.progress_file.read_text())['message'] == 'unlocked'


@pytest.mark.skipif(os.name != 'nt', reason='Real Windows sharing lock')
def test_real_windows_brief_reader_lock_recovers_inside_retry(tmp_path):
    log, _ = logger(tmp_path)
    ready = threading.Event()

    def reader():
        with deny_delete(log.progress_file):
            ready.set()
            time.sleep(.04)

    thread = threading.Thread(target=reader)
    thread.start()
    assert ready.wait(3)
    log('published after reader')
    thread.join(timeout=3)
    assert not log.progress_error
    assert json.loads(log.progress_file.read_text())['message'] == 'published after reader'
