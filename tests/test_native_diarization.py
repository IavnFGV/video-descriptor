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


@pytest.mark.parametrize('completed,total', [(None,10),(1,0),(1,None),(float('nan'),10),(1,float('inf')),(-1,10),(11,10),(True,10)])
def test_progress_never_invents_denominator_or_clamps_invalid_counts(completed, total):
    from video_descriptor.diarization_progress import progress_state
    value = progress_state('embeddings', completed=completed, total=total, at=100)
    assert 'completed' not in value and 'total' not in value


def test_progress_preserves_stage_start_but_not_previous_stage_percentage():
    from video_descriptor.diarization_progress import progress_state
    first = progress_state('embeddings', completed=3, total=10, at=100)
    next_value = progress_state('embeddings', first, 4, 10, at=105)
    assert next_value['stage_started_at'] == 100 and next_value['updated_at'] == 105
    clustering = progress_state('clustering', next_value, at=110)
    assert clustering['stage_started_at'] == 110 and 'completed' not in clustering


def test_measured_worker_progress_reaches_live_snapshot(recording, monkeypatch):
    from video_descriptor import live
    from video_descriptor.diarization_progress import progress_state
    root, _, video, settings = recording
    job = diarization.enqueue(root, 'source', settings)
    observed = []
    publish = diarization.publish

    def capture(path, result):
        publish(path, result)
        if path.name == 'speech.json' and result.get('diarization_progress', {}).get('stage') == 'embeddings':
            observed.append(live.snapshot(root, path.parent)['diarization_progress'])

    def process(command, **kwargs):
        output = Path(command[command.index('--output')+1])
        progress = Path(command[command.index('--progress')+1])
        jobs.write_json(progress, {**progress_state('embeddings', completed=3, total=10, at=100), 'message':'measured'})
        jobs.write_json(output, {'device':'cpu', 'duration':5,
            'audio_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),
            'turns':[{'start':0,'end':5,'speaker':'a'}]})
        return Mock(poll=Mock(side_effect=[None,0]), returncode=0)

    monkeypatch.setattr(diarization, 'publish', capture)
    monkeypatch.setattr(diarization, 'extract_audio', lambda source,target,start,duration: target.write_bytes(video.read_bytes()))
    monkeypatch.setattr(diarization.subprocess, 'Popen', process)
    monkeypatch.setattr(diarization.time, 'sleep', lambda seconds: None)
    diarization.run(root, root/'output/jobs'/job['id'], job, Mock())
    assert observed and observed[0]['completed'] == 3 and observed[0]['total'] == 10
    assert observed[0]['updated_at'] == 100
    assert live.snapshot(root, root/'output'/job['folder'])['diarization_progress']['stage'] == 'complete'
