import hashlib
import wave
from pathlib import Path
from unittest.mock import Mock

import pytest

from video_descriptor import diarization_postprocess as diarization
from video_descriptor import jobs


@pytest.fixture
def recording(tmp_path):
    video = tmp_path / 'data/sample.wav'
    video.parent.mkdir()
    with wave.open(str(video), 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\0\0' * 80000)
    source = tmp_path / 'output/source'
    source.mkdir(parents=True)
    rows = [{'id': 's1', 'start': 0, 'end': 2, 'text': 'Speech', 'speaker': 'unknown'},
            {'id': 's2', 'start': 3, 'end': 5, 'text': 'Reply', 'speaker': 'unknown'}]
    jobs.write_json(source / 'manifest.json', {'video': str(video)})
    jobs.write_json(source / 'speech.json', {'status': 'done', 'duration': 5, 'segments': rows,
                                           'video': 'data/sample.wav', 'title': 'Recording'})
    rows[0]['text'] = 'Corrected'
    jobs.write_json(source / 'transcript-edits.json', {'segments': rows, 'translations': {'s1': 'Перевод'}})
    model = tmp_path / 'model'
    model.mkdir()
    (model / 'config.yaml').write_text('local model')
    python = tmp_path / 'python.exe'
    python.touch()
    settings = {'diarization_python': str(python), 'diarization_model_directory': str(model),
                'diarization_device': 'cpu'}
    return tmp_path, source, video, settings


def test_snapshot_preserves_edits_translations_and_original(recording):
    root, source, _, settings = recording
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    job = diarization.enqueue(root, 'source', settings)
    target = root / 'output' / job['folder']
    assert jobs.read_json(target / 'speech.json')['segments'][0]['text'] == 'Corrected'
    assert jobs.read_json(target / 'translations.json') == {'s1': 'Перевод'}
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}
    assert job['task'] == 'diarize' and job['diarization_device'] == 'cpu'
    with pytest.raises(ValueError, match='уже находится'):
        diarization.enqueue(root, 'source', settings)


def test_worker_adds_only_speakers_without_asr_or_translation(recording, monkeypatch):
    root, source, video, settings = recording
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    job = diarization.enqueue(root, 'source', settings)
    calls = []

    def extract(source, target, start, duration):
        target.write_bytes(video.read_bytes())

    def process(command, **kwargs):
        calls.append(command)
        output = Path(command[command.index('--output') + 1])
        jobs.write_json(output, {'device': 'cpu', 'duration': 5,
                                'audio_sha256': hashlib.sha256(video.read_bytes()).hexdigest(),
                                'turns': [{'start': 0, 'end': 2, 'speaker': 'SPEAKER_00'},
                                          {'start': 3, 'end': 5, 'speaker': 'SPEAKER_01'}]})
        return Mock(poll=Mock(return_value=0), returncode=0)

    monkeypatch.setattr(diarization, 'extract_audio', extract)
    monkeypatch.setattr(diarization.subprocess, 'Popen', process)
    jobs.run_job(root, root / 'output/jobs' / job['id'], job)
    result = jobs.read_json(root / 'output' / job['folder'] / 'speech.json')
    assert job['status'] == result['status'] == 'done'
    assert [row['speaker'] for row in result['segments']] == ['SPEAKER_00', 'SPEAKER_01']
    assert [row['id'] for row in result['segments']] == ['s1', 's2']
    assert result['segments'][0]['text'] == 'Corrected'
    assert len(calls) == 1 and calls[0][4].endswith('diarization_worker.py')
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}


@pytest.mark.parametrize('turns', [[{'start': 0, 'end': -1, 'speaker': 'a'}],
                                 [{'start': float('nan'), 'end': 2, 'speaker': 'a'}],
                                 [{'start': 0, 'end': 99, 'speaker': 'a'}]])
def test_invalid_speaker_boundaries_are_not_saved(turns):
    with pytest.raises(ValueError, match='границы'):
        diarization.validate_turns(turns, 5)


def test_model_change_does_not_silently_reuse_results(recording):
    root, _, _, settings = recording
    job = diarization.enqueue(root, 'source', settings)
    (Path(settings['diarization_model_directory']) / 'config.yaml').write_text('changed')
    with pytest.raises(RuntimeError, match='Модель диаризации изменилась'):
        diarization.run(root, root / 'output/jobs' / job['id'], job, Mock())
    assert jobs.read_json(root / 'output' / job['folder'] / 'speech.json')['status'] == 'error'


def test_progress_publish_retries_windows_read_handle(tmp_path, monkeypatch):
    original = diarization.write_json
    attempts = []

    def write(path, value):
        attempts.append(path)
        if len(attempts) == 1:
            raise PermissionError('file temporarily open for reading')
        original(path, value)

    monkeypatch.setattr(diarization, 'write_json', write)
    monkeypatch.setattr(diarization.time, 'sleep', lambda seconds: None)
    path = tmp_path / 'progress.json'
    diarization.publish(path, {'message': 'running'})
    assert jobs.read_json(path) == {'message': 'running'}
    assert len(attempts) == 2
