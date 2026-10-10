from unittest.mock import Mock

import pytest

from video_descriptor import construction, jobs, live, translation_settings


def recording(root):
    video = root / 'data' / 'recording.mp4'
    video.parent.mkdir()
    video.write_bytes(b'video')
    folder = root / 'output' / 'original'
    folder.mkdir(parents=True)
    jobs.write_json(folder / 'manifest.json', {'video': str(video), 'processed_duration': 30})
    rows = [{'id': 's1', 'start': 0, 'end': 10, 'text': 'Original speech', 'speaker': 'speaker_1'}]
    jobs.write_json(folder / 'transcript.json', rows)
    jobs.write_json(folder / 'speech.json', {'folder': folder.name, 'status': 'done',
                                           'engine': 'whisper', 'segments': rows})
    jobs.write_json(folder / 'frames.json', [
        {'id': 'f1', 'start': 0, 'end': 10, 'text': 'Slide text', 'image': 'frames/f1.jpg'}])
    (folder / 'frames').mkdir()
    (folder / 'frames' / 'f1.jpg').write_bytes(b'image')
    (folder / 'report.html').write_text('Original report')
    jobs.write_json(folder / 'notes.json', {'notes': [], 'sections': []})
    (folder / 'notes.user.md').write_text('Personal notes')
    return folder


def test_notes_strategy_explicitly_selects_slide_text(tmp_path):
    folder = recording(tmp_path)
    _, speech_lines, frames = construction.material(folder, construction.validate({'input': 'speech'}))
    assert frames == []
    assert len(speech_lines) == 1
    _, slide_lines, frames = construction.material(folder, construction.validate({'input': 'slides'}))
    assert len(frames) == 1
    assert any('Slide text' in row['text'] for row in slide_lines)
    with pytest.raises(ValueError):
        construction.validate({'input': 'whole-video'})


def test_rerun_notes_creates_independent_version_and_copies_corrected_sources(tmp_path, monkeypatch):
    folder = recording(tmp_path)
    jobs.write_json(folder / 'transcript-edits.json', {'segments': [
        {'id': 's1', 'start': 0, 'end': 10, 'text': 'Corrected speech', 'speaker': 'speaker_1'}]})
    before = {path.name: path.read_bytes() for path in folder.iterdir() if path.is_file()}
    job = construction.enqueue_notes(tmp_path, folder.name, {'input': 'slides'})
    version = tmp_path / 'output' / job['folder']
    assert version != folder
    assert job['source_folder'] == folder.name
    assert jobs.read_json(version / 'manifest.json')['version_of'] == folder.name
    assert (version / 'frames' / 'f1.jpg').read_bytes() == b'image'
    assert not (version / 'notes.user.md').exists()
    assert not (version / 'report.html').exists()
    assert before == {path.name: path.read_bytes() for path in folder.iterdir() if path.is_file()}
    _, lines, _ = construction.material(version, construction.validate({'input': 'speech'}))
    assert 'Corrected speech' in lines[0]['text']
    monkeypatch.setattr(live, 'active_video', lambda path: False)
    snapshot = live.snapshot(tmp_path, version)
    assert snapshot['phase'] == 4
    assert snapshot['status']['message'] == 'Конспект в очереди'
    assert snapshot['previous_report_url'] == '/output/original/report.html'
    assert not snapshot['report_url']
    assert snapshot['source_video'] == 'data/recording.mp4'
    assert len(live.runs(tmp_path)) == 2


def test_speech_only_rerun_does_not_build_notes_or_translate(tmp_path, monkeypatch):
    folder = recording(tmp_path)
    job = {'id': 'a' * 32, 'video': str(tmp_path / 'data' / 'recording.mp4'),
           'filename': 'recording.mp4', 'mode': 'audio', 'engine': 'whisper',
           'folder': folder.name, 'title': '', 'thinking': False, 'speech_only': True}
    job_folder = jobs.jobs_dir(tmp_path) / job['id']
    job_folder.mkdir()
    run = Mock()
    monkeypatch.setattr(jobs.subprocess, 'run', run)
    jobs.run_job(tmp_path, job_folder, job)
    run.assert_not_called()
    assert jobs.read_json(job_folder / 'job.json')['status'] == 'done'
    assert (folder / 'notes.user.md').read_text() == 'Personal notes'


def test_video_pipeline_uses_selected_speech_engine_and_slide_strategy(tmp_path, monkeypatch):
    folder = recording(tmp_path)
    job = {'id': 'b' * 32, 'video': str(tmp_path / 'data' / 'recording.mp4'),
           'filename': 'recording.mp4', 'mode': 'lecture', 'engine': 'whisper',
           'folder': folder.name, 'title': '', 'thinking': False,
           'construction': construction.validate({'input': 'slides'})}
    job_folder = jobs.jobs_dir(tmp_path) / job['id']
    job_folder.mkdir()
    commands = []
    monkeypatch.setattr(jobs.subprocess, 'run', lambda command, **kw: commands.append(command) or Mock(returncode=0))
    jobs.run_job(tmp_path, job_folder, job)
    assert [command[3] for command in commands] == [
        'video_descriptor', 'video_descriptor.construction', 'video_descriptor.translate']
    assert '--speech-result' in commands[0]
    assert '--skip-notes' in commands[0]
    assert '--audio-only' not in commands[0]


def test_translation_settings_accept_local_model_without_changing_cloud_key(tmp_path):
    translation_settings.save(tmp_path, {'api_key': 'private-key'})
    settings = translation_settings.save(tmp_path, {'provider': 'ollama', 'ollama_model': 'local-model:latest'})
    assert settings['ollama_model'] == 'local-model:latest'
    assert settings['has_key']
    assert 'api_key' not in settings
    with pytest.raises(ValueError):
        translation_settings.save(tmp_path, {'ollama_model': 'invalid model'})
