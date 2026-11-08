import importlib.util
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from video_descriptor.jobs import write_json
from video_descriptor.recording import variants


def result(root, name, video, model=''):
    folder = root / 'output' / name
    folder.mkdir(parents=True)
    write_json(folder / 'manifest.json', {'video': str(video)})
    write_json(folder / 'speech.json', {'status': 'done', 'engine': 'whisper-local'})
    if model:
        (folder / 'report.html').write_text('report')
        write_json(folder / 'notes.json', {})
        write_json(folder / 'construction-settings.json', {'model': model, 'api_key': 'never-return'})
    return folder


def test_recording_groups_by_source_and_keeps_report_source_snapshot(tmp_path):
    video = tmp_path / 'data' / 'one.mp4'
    video.parent.mkdir()
    video.write_bytes(b'video')
    result(tmp_path, 'original', video)
    result(tmp_path, 'notes', video, 'chosen-model')
    result(tmp_path, 'different-recording', tmp_path / 'data' / 'other.mp4', 'other-model')
    data = variants(tmp_path, folder='original')
    assert {item['folder'] for item in data['speech']} == {'original', 'notes'}
    assert len(data['reports']) == 1
    assert data['reports'][0]['speech_folder'] == 'notes'
    assert data['reports'][0]['model'] == 'chosen-model'
    assert 'never-return' not in str(data)
    assert data['video_url'] == '/data/one.mp4'


def test_queued_recording_has_player_before_transcript_exists(tmp_path):
    job = 'a' * 32
    (tmp_path / 'output' / 'jobs' / job).mkdir(parents=True)
    write_json(tmp_path / 'output' / 'jobs' / job / 'job.json',
               {'video': str(tmp_path / 'data' / 'one.mp4'), 'status': 'queued', 'folder': None})
    data = variants(tmp_path, job=job)
    assert data['video_url'] == '/data/one.mp4'
    assert data['speech'] == []


@pytest.mark.parametrize('name', ['..', '../outside', '.', 'missing'])
def test_recording_rejects_missing_and_traversal(tmp_path, name):
    with pytest.raises(ValueError):
        variants(tmp_path, folder=name)


def test_completed_transcript_remains_complete_during_other_processing(tmp_path, monkeypatch):
    from video_descriptor import live
    video = tmp_path / 'data' / 'one.mp4'
    folder = result(tmp_path, 'original', video)
    rows = [{'id': str(i), 'start': i, 'end': i+1, 'text': str(i)} for i in range(100)]
    write_json(folder / 'transcript.json', rows)
    monkeypatch.setattr(live, 'active_video', lambda _: True)
    assert len(live.snapshot(tmp_path, folder)['speech']) == 100


def test_live_edit_revision_matches_saved_speech_and_changes_after_edit(tmp_path, monkeypatch):
    from video_descriptor import live, speech
    folder = result(tmp_path, 'original', tmp_path / 'data' / 'one.mp4')
    rows = [{'id': 's1', 'start': 0, 'end': 5, 'text': 'Original', 'speaker': 'unknown'}]
    write_json(folder / 'speech.json', {'status': 'done', 'segments': rows})
    write_json(folder / 'transcript.json', rows)
    monkeypatch.setattr(live, 'active_video', lambda _: False)
    initial = live.snapshot(tmp_path, folder)
    assert initial['speech_edit_revision'] == speech.state(tmp_path, {'folder': ['original']})['result']['edit_revision']
    speech.edit_utterance(tmp_path, {'folder': 'original', 'revision': initial['speech_edit_revision'],
                                   'index': 0, 'action': 'edit', 'text': 'Corrected', 'speaker': 'unknown', 'translation': ''})
    updated = live.snapshot(tmp_path, folder)
    assert updated['speech_edit_revision'] != initial['speech_edit_revision']
    assert updated['speech'][0]['text'] == 'Corrected'
    assert 'unknown' in updated['speaker_options']


def test_native_rerun_pins_device_without_copying_source_or_starting_inference(tmp_path, monkeypatch):
    from video_descriptor import jobs
    spec = importlib.util.spec_from_file_location('recording_native_app', Path(__file__).resolve().parents[1] / 'windows-app/app.py')
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    import compute
    import setup_service
    monkeypatch.setattr(setup_service.SetupService, 'bootstrap', lambda self: None)
    plan = {'requested': 'GPU', 'selected': 'GPU', 'backend': {'device': 'GPU'}}
    monkeypatch.setattr(compute.ComputeManager, 'make_plan', lambda self, requested: plan)
    start = Mock()
    monkeypatch.setattr(jobs, 'start_worker', start)
    video = tmp_path / 'data' / 'one.mp4'
    video.parent.mkdir()
    video.write_bytes(b'original-video')
    result(tmp_path, 'original', video)
    value = {'workspace': str(tmp_path), 'npu_worker_directory': str(tmp_path / 'benchmark'),
             'ollama_url': 'http://127.0.0.1:11434'}
    with ThreadingHTTPServer(('127.0.0.1', 0), app.make_handler(value, 'instance')) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            body = {'video': 'data/one.mp4', 'engine': 'whisper-local', 'device': 'GPU'}
            assert requests.post(base + '/api/speech-run', json=body, headers={'Origin': 'https://other.invalid'}, timeout=5).status_code == 403
            response = requests.post(base + '/api/speech-run', json=body, timeout=5)
            assert response.status_code == 202, response.text
            job = response.json()
            assert job['device_plan'] == plan
            assert job['video'] == str(video)
            assert job['speech_only'] is True
            assert video.read_bytes() == b'original-video'
            assert requests.post(base + '/api/speech-run', json=body, timeout=5).status_code == 400
            view = requests.get(base + '/api/recording?folder=original', timeout=5).json()
            assert view['active_job']['id'] == job['id']
            start.assert_called_once()
        finally:
            server.shutdown()
            thread.join()


def test_internal_report_snapshots_are_identified_without_losing_artifacts(tmp_path):
    video = tmp_path / 'data' / 'one.mp4'
    result(tmp_path, 'original', video)
    folder = result(tmp_path, 'snapshot', video, 'chosen-model')
    write_json(folder / 'construction-job.json', {'id': 'a' * 32})
    data = variants(tmp_path, folder='snapshot')
    visible = [item['folder'] for item in data['speech'] if not item['internal_snapshot']]
    assert visible == ['original']
    assert data['reports'][0]['speech_folder'] == 'snapshot'
    assert (folder / 'speech.json').is_file()
