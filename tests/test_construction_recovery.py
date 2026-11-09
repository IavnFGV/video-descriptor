import threading
from functools import partial
from http.server import ThreadingHTTPServer

import pytest
import requests

from video_descriptor import construction, jobs, serve
from video_descriptor.construction_recovery import recover
from video_descriptor.editor import EditConflict

RAW = '## Оглавление\n### [00:00:05] Topic\n\n## Конспект\n### [00:00:05] Topic\nSummary.'
FIXED = RAW.replace('00:00:05', '00:00:10')


def setup_failed(root):
    folder = root / 'output/processed-test'
    folder.mkdir(parents=True)
    job_folder = root / ('output/jobs/' + 'a' * 32)
    job_folder.mkdir(parents=True)
    jobs.write_json(folder / 'manifest.json', {'video': str(root / 'video.mp4')})
    jobs.write_json(folder / 'speech.json', {'status': 'done', 'segments': [
        {'id': 's1', 'start': 10, 'end': 20, 'text': 'Topic source', 'speaker': 'unknown'}], 'translations': {}})
    jobs.write_json(folder / 'construction-settings.json', construction.validate({}))
    jobs.write_json(folder / 'construction-error.json', {'error': 'invalid timestamp'})
    (folder / 'construction-result.md').write_text(RAW, encoding='utf-8')
    jobs.write_json(job_folder / 'job.json', {'id': 'a' * 32, 'task': 'notes',
                    'mode': 'postprocess', 'folder': folder.name, 'status': 'error'})
    return folder, job_folder


def test_manual_recovery_preserves_raw_and_never_calls_model(tmp_path, monkeypatch):
    folder, job_folder = setup_failed(tmp_path)
    state = recover(tmp_path, {'folder': folder.name})
    assert state['text'] == RAW and state['anchors'][0]['time'] == 10
    result = recover(tmp_path, {'folder': folder.name, 'revision': state['revision'], 'text': FIXED})
    assert result['job']['status'] == 'queued'
    monkeypatch.setattr(construction, 'validate_provider', lambda *args: pytest.fail('provider called'))
    monkeypatch.setattr(construction, 'render', lambda *args: None)
    construction.run(tmp_path, folder, {}, ask=lambda *args: pytest.fail('model called'))
    assert (folder / 'construction-result.md').read_text(encoding='utf-8') == RAW
    assert (folder / 'editor-default.md').read_text(encoding='utf-8') == FIXED
    assert jobs.read_json(folder / 'chapters.json')[0]['start'] == 10
    assert not (folder / 'construction-error.json').exists()
    assert jobs.read_json(job_folder / 'job.json')['status'] == 'queued'


def test_invalid_edit_is_not_saved_or_queued(tmp_path):
    folder, job_folder = setup_failed(tmp_path)
    state = recover(tmp_path, {'folder': folder.name})
    with pytest.raises(ValueError, match='00:00:05'):
        recover(tmp_path, {'folder': folder.name, 'revision': state['revision'], 'text': RAW})
    assert not (folder / 'construction-manual.json').exists()
    assert jobs.read_json(job_folder / 'job.json')['status'] == 'error'


def test_stale_source_or_active_job_cannot_be_overwritten(tmp_path):
    folder, job_folder = setup_failed(tmp_path)
    state = recover(tmp_path, {'folder': folder.name})
    (folder / 'construction-result.md').write_text(RAW + '\nChanged', encoding='utf-8')
    with pytest.raises(EditConflict):
        recover(tmp_path, {'folder': folder.name, 'revision': state['revision'], 'text': FIXED})
    job = jobs.read_json(job_folder / 'job.json')
    job['status'] = 'running'
    jobs.write_json(job_folder / 'job.json', job)
    with pytest.raises(ValueError, match='завершения'):
        recover(tmp_path, {'folder': folder.name})


def test_edited_source_after_save_blocks_cached_manual_result(tmp_path, monkeypatch):
    folder, _ = setup_failed(tmp_path)
    state = recover(tmp_path, {'folder': folder.name})
    recover(tmp_path, {'folder': folder.name, 'revision': state['revision'], 'text': FIXED})
    speech = jobs.read_json(folder / 'speech.json')
    speech['segments'][0]['start'] = 11
    jobs.write_json(folder / 'speech.json', speech)
    with pytest.raises(ValueError, match='изменились'):
        construction.run(tmp_path, folder, {})


def test_recovery_http_conflict_origin_and_success(tmp_path, monkeypatch):
    folder, _ = setup_failed(tmp_path)
    started = []
    monkeypatch.setattr(serve, 'start_worker', lambda root: started.append(root))
    server = ThreadingHTTPServer(('127.0.0.1', 0),
                                partial(serve.RangeRequestHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/api/construction-recovery'
    try:
        response = requests.post(url, json={'folder': folder.name}, timeout=5)
        assert response.status_code == 200
        revision = response.json()['revision']
        denied = requests.post(url, json={'folder': folder.name},
                               headers={'Origin': 'http://untrusted.example'}, timeout=5)
        assert denied.status_code == 403
        conflict = requests.post(url, json={'folder': folder.name, 'text': FIXED,
                                           'revision': 'stale'}, timeout=5)
        assert conflict.status_code == 409 and not started
        checked = requests.post(url, json={'folder': folder.name, 'text': FIXED,
                                           'revision': revision, 'action': 'validate'}, timeout=5)
        assert checked.status_code == 200 and checked.json() == {'valid': True, 'issues': []}
        assert not started and not (folder / 'construction-manual.json').exists()
        saved = requests.post(url, json={'folder': folder.name, 'text': FIXED,
                                        'revision': revision}, timeout=5)
        assert saved.status_code == 200 and saved.json()['job']['status'] == 'queued'
        assert started == [tmp_path.resolve()]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_recovery_reports_all_locations_and_dry_run_never_saves(tmp_path):
    folder, job_folder = setup_failed(tmp_path)
    state = recover(tmp_path, {'folder': folder.name})
    assert [issue['line'] for issue in state['issues']] == [2, 5]
    assert all(issue['code'] == 'unknown_time' for issue in state['issues'])
    assert state['issues'][0]['candidates'] == [{'time': '00:00:10', 'text': 'Topic source'}]
    checked = recover(tmp_path, {'folder': folder.name, 'revision': state['revision'],
                                 'text': FIXED, 'action': 'validate'})
    assert checked == {'issues': [], 'valid': True}
    assert not (folder / 'construction-manual.json').exists()
    assert jobs.read_json(job_folder / 'job.json')['status'] == 'error'
    assert (folder / 'construction-result.md').read_text(encoding='utf-8') == RAW


def test_validation_offsets_select_exact_duplicate_after_emoji():
    from video_descriptor.models import Source
    from video_descriptor.notes_validation import notes_issues
    text = '😀\n' + RAW
    issues = notes_issues(text, [Source(id='s', start=10, end=20, text='Source')])
    encoded = text.encode('utf-16-le')
    assert len(issues) == 2
    for issue in issues:
        assert encoded[issue['start'] * 2:issue['end'] * 2].decode('utf-16-le') == '00:00:05'
    assert issues[1]['start'] > issues[0]['end']


def test_diagnostics_distinguish_chronology_and_ranges():
    from video_descriptor.models import Source
    from video_descriptor.notes_validation import notes_issues
    sources = [Source(id='a', start=10, end=20, text='A'), Source(id='b', start=30, end=40, text='B')]
    text = '## Оглавление\n### [00:00:30] Later\n### [00:00:10] Earlier\n## Конспект\n### [00:00:10–00:00:20] Topic\nText'
    issues = notes_issues(text, sources)
    assert [issue['code'] for issue in issues] == ['chronology']
    assert issues[0]['line'] == 3 and '00:00:30' in issues[0]['message']
    assert notes_issues(text.replace('00:00:20', '00:00:09'), sources)[-1]['code'] == 'range'


def test_diagnostics_explain_missing_sections_and_malformed_headings():
    from video_descriptor.models import Source
    from video_descriptor.notes_validation import notes_issues
    sources = [Source(id='a', start=10, end=20, text='A')]
    assert notes_issues('# Just text', sources)[0]['code'] == 'sections'
    assert notes_issues('## Оглавление\n### 00:00:10 Topic\n## Конспект\n### [00:00:10] Topic', sources)[0]['code'] == 'heading'
