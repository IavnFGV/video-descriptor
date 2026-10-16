import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

from video_descriptor import jobs, speech, speech_npu
from video_descriptor.platform_support import environment_python, lock_file
from video_descriptor.subtitles import subrip


def native():
    spec = importlib.util.spec_from_file_location('native_app', Path(__file__).resolve().parents[1] / 'windows-app/app.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_speech_publishes_job_folder_after_manifest_exists(tmp_path, monkeypatch):
    video = tmp_path / 'data/test.mp4'
    video.parent.mkdir()
    video.write_bytes(b'test')
    job_folder = tmp_path / 'output/jobs/test'
    job_folder.mkdir(parents=True)
    job = {'id': 'test', 'video': str(video), 'engine': 'whisper-local', 'title': ''}
    monkeypatch.setattr(speech, 'probe', lambda _: {'format': {'duration': '20'}})

    def capture(path, value):
        if path == job_folder / 'job.json':
            assert (tmp_path / 'output' / value['folder'] / 'manifest.json').is_file()
            raise RuntimeError('publication verified')
        jobs.write_json(path, value)

    monkeypatch.setattr(speech, 'write_json', capture)
    with pytest.raises(RuntimeError, match='publication verified'):
        speech.run(tmp_path, job_folder, job)


def test_actual_lock_excludes_other_process_and_releases_on_close(tmp_path):
    path = tmp_path / 'worker.lock'
    script = '''
import sys
from video_descriptor.platform_support import lock_file
with open(sys.argv[1], 'a+') as stream:
    try:
        lock_file(stream)
    except BlockingIOError:
        raise SystemExit(23)
'''
    with path.open('a+') as stream:
        lock_file(stream)
        blocked = subprocess.run([sys.executable, '-c', script, str(path)], check=False)
        assert blocked.returncode == 23
    assert subprocess.run([sys.executable, '-c', script, str(path)], check=False).returncode == 0


def test_venv_interpreter_uses_platform_and_explicit_override(tmp_path, monkeypatch):
    monkeypatch.delenv('VIDEO_DESCRIPTOR_DIARIZATION_PYTHON', raising=False)
    path = environment_python(tmp_path, '.venv-diarization-xpu')
    assert path.parts[-2:] == (('Scripts', 'python.exe') if os.name == 'nt' else ('bin', 'python'))
    monkeypatch.setenv('VIDEO_DESCRIPTOR_DIARIZATION_PYTHON', str(tmp_path / 'external/python.exe'))
    assert environment_python(tmp_path, 'ignored') == tmp_path / 'external/python.exe'


def test_native_loopback_configuration_and_workspace_isolation(tmp_path, monkeypatch):
    module = native()
    monkeypatch.setattr(module, 'HERE', tmp_path)
    settings = {'port': 8780, 'workspace': 'runtime/workspace',
                'npu_url': 'http://127.0.0.1:8766', 'ollama_url': 'http://localhost:11434',
                'npu_worker_directory': '', 'diarization_python': '', 'ollama_model': 'qwen3.5:9b'}
    file = tmp_path / 'config.example.json'
    file.write_text(json.dumps(settings), encoding='utf-8')
    assert Path(module.config()['workspace']) == tmp_path / 'runtime/workspace'
    file.write_text(json.dumps({**settings, 'workspace': '../original-project'}), encoding='utf-8')
    with pytest.raises(ValueError):
        module.config()
    file.write_text(json.dumps({**settings, 'npu_url': 'https://example.com'}), encoding='utf-8')
    with pytest.raises(ValueError, match='локальный'):
        module.config()


def test_native_stop_checks_instance_and_refuses_active_queue(tmp_path):
    module = native()
    value = {'workspace': str(tmp_path)}
    handler = module.make_handler(value, 'owned-instance')
    with ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            assert requests.get(base + '/health', timeout=3).json()['app'] == module.APP
            assert requests.post(base + '/api/native/stop', timeout=3).status_code == 403
            job = tmp_path / 'output/jobs/abc/job.json'
            job.parent.mkdir(parents=True)
            jobs.write_json(job, {'status': 'running'})
            assert requests.post(base + '/api/native/stop', headers={'X-App-Instance': 'owned-instance'}, timeout=3).status_code == 409
        finally:
            server.shutdown()
            thread.join()


def test_srt_preserves_timing_and_joins_translation_cues():
    result = {'segments': [{'id': 'a', 'start': 1.234, 'end': 2, 'text': 'Hello'},
                           {'id': 'b', 'start': 2, 'end': 3.5, 'text': 'there'}],
              'translations': {'a': 'Привет', 'b': ''}}
    assert subrip(result, 'ru') == '1\n00:00:01,234 --> 00:00:03,500\nПривет\n'
    assert '00:00:02,000 --> 00:00:03,500' in subrip(result)


def test_timing_edit_preserves_id_and_original_and_rejects_stale_revision(tmp_path):
    folder = tmp_path / 'output/speech-test'
    folder.mkdir(parents=True)
    original = {'status': 'done', 'duration': 10, 'segments': [
        {'id': 's00001', 'start': 1, 'end': 5, 'text': 'Original', 'speaker': 'unknown'}]}
    jobs.write_json(folder / 'speech.json', original)
    revision = speech.editable_result(folder, original)['edit_revision']
    changes = {'folder': folder.name, 'revision': revision, 'index': 0, 'action': 'edit',
               'text': 'Corrected', 'speaker': 'unknown', 'start': 1.25, 'end': 4.75}
    result = speech.edit_utterance(tmp_path, changes)
    assert result['segments'][0]['id'] == 's00001'
    assert result['segments'][0]['start'] == 1.25
    assert jobs.read_json(folder / 'speech.json') == original
    with pytest.raises(ValueError, match='изменились'):
        speech.edit_utterance(tmp_path, changes)
    with pytest.raises(ValueError, match='границы'):
        speech.edit_utterance(tmp_path, {**changes, 'revision': result['edit_revision'], 'end': 20})


def test_missing_npu_end_is_not_fabricated():
    with pytest.raises(ValueError, match='end_ts=-1'):
        speech_npu.timed_items({'segments': [{'start': 0, 'end': -1, 'text': 'unclosed'}]}, 600, 30)


def test_npu_language_change_does_not_reuse_other_language_cache(tmp_path, monkeypatch):
    monkeypatch.setenv('SPEECH_LANGUAGE', 'uk')
    monkeypatch.setattr(speech_npu, 'health', lambda: {'device': 'NPU'})
    jobs.write_json(tmp_path / 'npu-language.json', {'language': 'en'})
    with pytest.raises(ValueError, match='Язык изменился'):
        speech_npu.transcribe(tmp_path / 'not-opened.wav', tmp_path, lambda *args: None, lambda *args: None)


def test_failure_before_audio_preparation_still_has_retryable_job_state(tmp_path):
    job_id = 'b' * 32
    file = tmp_path / 'output/jobs' / job_id / 'job.json'
    file.parent.mkdir(parents=True)
    job = {'id': job_id, 'mode': 'audio', 'status': 'error', 'error': 'Invalid video', 'folder': 'speech-bad'}
    jobs.write_json(file, job)
    assert speech.state(tmp_path, {'job': [job_id]}) == {'job': job, 'result': None}
