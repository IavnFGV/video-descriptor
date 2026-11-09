import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer

import pytest
import requests

from video_descriptor.action_history import record
from video_descriptor.jobs import read_json, write_json
from video_descriptor.request_log import RequestJournal
from video_descriptor.serve import RangeRequestHandler


@pytest.fixture(autouse=True)
def isolated_journal_environment(monkeypatch):
    monkeypatch.delenv('VIDEO_DESCRIPTOR_EVENTS', raising=False)
    monkeypatch.delenv('VIDEO_DESCRIPTOR_WORKSPACE', raising=False)


def test_model_request_lifecycle_and_safe_metadata(tmp_path, monkeypatch):
    global_log = tmp_path / 'global.jsonl'
    monkeypatch.setenv('VIDEO_DESCRIPTOR_EVENTS', str(global_log))
    request = RequestJournal(tmp_path / 'recording/requests', 'http://local',
                             {'model': 'chosen', 'prompt': 'PRIVATE'}, {}, 'construction')
    request.event({'message': {'content': 'PRIVATE ANSWER'}})
    request.finish('done')
    events = [json.loads(line) for line in global_log.read_text(encoding='utf-8').splitlines()]
    assert [event['action'] for event in events] == ['model_request_started', 'model_request_finished']
    assert events[0]['request_id'] == events[1]['request_id']
    assert events[1]['received'] == len('PRIVATE ANSWER')
    assert 'PRIVATE' not in global_log.read_text(encoding='utf-8')
    assert (tmp_path / 'recording/application-events.jsonl').is_file()
    record('settings_changed', path=global_log, api_key='SECRET', prompt='SECRET', token='SECRET')
    assert 'SECRET' not in global_log.read_text(encoding='utf-8')


def test_http_mutations_have_one_correlated_start_and_result(tmp_path):
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(RangeRequestHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        response = requests.post(base + '/api/construction-settings?token=SECRET',
                                 json={'model': 'selected'}, timeout=5)
        assert response.status_code == 200
        bad = requests.post(base + '/api/construction-settings', json={'unknown': 'SECRET'}, timeout=5)
        assert bad.status_code == 400
        events = [json.loads(line) for line in (tmp_path / 'output/application-events.jsonl').read_text(encoding='utf-8').splitlines()]
        # The server writes completion after sending the response; wait for its thread.
        for _ in range(100):
            events = [json.loads(line) for line in (tmp_path / 'output/application-events.jsonl').read_text(encoding='utf-8').splitlines()]
            if len(events) == 4:
                break
            threading.Event().wait(.01)
        assert [event['action'] for event in events] == ['operation_started', 'operation_finished', 'operation_started', 'operation_failed']
        assert events[0]['operation_id'] == events[1]['operation_id']
        assert events[2]['operation_id'] == events[3]['operation_id']
        assert events[3]['code'] == 400
        assert 'SECRET' not in json.dumps(events)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_worker_event_resolves_recording_from_job(tmp_path, monkeypatch):
    monkeypatch.setenv('VIDEO_DESCRIPTOR_WORKSPACE', str(tmp_path))
    job = tmp_path / ('output/jobs/' + 'a' * 32) / 'job.json'
    job.parent.mkdir(parents=True)
    write_json(job, {'folder': 'recording'})
    record('job_finished', job_id='a' * 32, status='done')
    events = (tmp_path / 'output/recording/application-events.jsonl').read_text(encoding='utf-8')
    assert json.loads(events)['folder'] == 'recording'
    assert read_json(job) == {'folder': 'recording'}


def test_locked_record_journal_keeps_global_event_without_failing_operation(tmp_path, monkeypatch, caplog):
    from video_descriptor import action_history
    target = tmp_path / 'global.jsonl'
    monkeypatch.setenv('VIDEO_DESCRIPTOR_EVENTS', str(target))
    original = action_history.append_event
    def append(path, event):
        if path != target:
            raise PermissionError('locked')
        original(path, event)
    monkeypatch.setattr(action_history, 'append_event', append)
    assert record('notes_saved', folder=tmp_path / 'recording', status='done')
    events = [json.loads(line) for line in target.read_text(encoding='utf-8').splitlines()]
    assert [e['action'] for e in events] == ['notes_saved', 'journal_delivery_failed']
    assert 'Journal delivery failed' in caplog.text
