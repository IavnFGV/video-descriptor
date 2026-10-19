import sys
import threading
import time

import pytest

from video_descriptor import jobs


def test_stop_queued_and_reject_path(tmp_path):
    identity = 'a' * 32
    folder = jobs.jobs_dir(tmp_path) / identity
    folder.mkdir()
    jobs.write_json(folder / 'job.json', {'id': identity, 'status': 'queued'})
    assert jobs.request_stop(tmp_path, identity)['cancelled']
    jobs.run_job(tmp_path, folder, jobs.read_json(folder / 'job.json'))
    assert jobs.read_json(folder / 'job.json')['status'] == 'error'
    with pytest.raises(ValueError):
        jobs.request_stop(tmp_path, '../outside')


def test_stop_running_process(tmp_path):
    marker = tmp_path / 'started'
    def cancel():
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        jobs.write_json(tmp_path / 'stop-request.json', {})
    thread = threading.Thread(target=cancel)
    thread.start()
    with pytest.raises(jobs.JobStopped):
        jobs.run_process(tmp_path, [sys.executable, '-c',
                         'from pathlib import Path; import time; Path(' + repr(str(marker)) + ').touch(); time.sleep(60)'])
    thread.join(timeout=10)
    assert marker.exists()


def test_completed_job_is_untouched(tmp_path):
    identity = 'b' * 32
    folder = jobs.jobs_dir(tmp_path) / identity
    folder.mkdir()
    job = {'id': identity, 'status': 'done'}
    jobs.write_json(folder / 'job.json', job)
    assert jobs.request_stop(tmp_path, identity) == job
    assert not (folder / 'stop-request.json').exists()


def test_running_job_records_stop_and_preserves_segments(tmp_path, monkeypatch):
    from video_descriptor import postprocess
    identity = 'c' * 32
    folder = jobs.jobs_dir(tmp_path) / identity
    folder.mkdir()
    result = tmp_path / 'output' / 'version'
    result.mkdir()
    rows = [{'start': 0, 'end': 1, 'text': 'Saved speech'}]
    jobs.write_json(result / 'speech.json', {'status': 'running', 'segments': rows})
    job = {'id': identity, 'status': 'queued', 'mode': 'postprocess', 'task': 'diarize', 'folder': 'version'}
    jobs.write_json(folder / 'job.json', job)
    def run(root, job_folder, value, log):
        jobs.request_stop(root, value['id'])
        jobs.check_stop(job_folder)
    monkeypatch.setattr(postprocess, 'run', run)
    jobs.run_job(tmp_path, folder, job)
    saved = jobs.read_json(folder / 'job.json')
    assert saved['cancelled'] and saved['status'] == 'error'
    assert jobs.read_json(result / 'speech.json')['segments'] == rows
