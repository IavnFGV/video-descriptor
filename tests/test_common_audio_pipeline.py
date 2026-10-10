import json
import sys
from unittest.mock import Mock

from video_descriptor import __main__ as cli, jobs, live
from video_descriptor.models import Note, Notes


def test_audio_builds_notes_and_report_from_recognized_speech(tmp_path, monkeypatch):
    video = tmp_path / 'meeting.wav'
    video.write_bytes(b'audio')
    folder = tmp_path / 'output' / 'speech-example'
    folder.mkdir(parents=True)
    jobs.write_json(folder / 'manifest.json', {'video': str(video)})
    jobs.write_json(folder / 'speech.json', {
        'status': 'done', 'engine': 'whisper', 'segments': [
            {'start': 0, 'end': 10, 'text': 'Learning about cloud computing', 'speaker': 'speaker_1'}],
    })
    monkeypatch.setattr(sys, 'argv', ['video_descriptor', str(video), '--model', 'model',
                                     '--audio-only', '--speech-result', str(folder / 'speech.json')])
    monkeypatch.setattr(cli, 'probe', lambda path: {
        'format': {'duration': '60'}, 'streams': [{'codec_type': 'audio'}],
    })
    for name in ['extract_audio', 'transcribe', 'extract_frames', 'check_vision_model', 'frame_changes']:
        monkeypatch.setattr(cli, name, Mock(side_effect=AssertionError(f'{name} must be skipped')))
    summarize = Mock(return_value=Notes(notes=[Note(
        title='Cloud', explanation='Cloud computing', steps=[], limitations=[], source_ids=['s1'])]))
    monkeypatch.setattr(cli, 'summarize', summarize)
    monkeypatch.setattr(cli, 'filter_notes', lambda result, *args: result)
    assert cli.main() == 0
    assert summarize.call_count == 1
    assert json.loads((folder / 'frames.json').read_text()) == []
    assert json.loads((folder / 'manifest.json').read_text())['mode'] == 'audio'
    assert 'Cloud' in (folder / 'report.html').read_text()
    assert 'Cloud' in (folder / 'notes.md').read_text()
    assert (folder / 'original.vtt').exists()
    # Continuing keeps the completed notes, just like the video pipeline.
    assert cli.main() == 0
    assert summarize.call_count == 1


def test_audio_job_runs_common_pipeline_and_translation_after_recognition(tmp_path, monkeypatch):
    video = tmp_path / 'data' / 'meeting.wav'
    video.parent.mkdir()
    video.write_bytes(b'audio')
    job = {'id': 'a' * 32, 'video': str(video), 'filename': video.name,
           'title': 'Meeting', 'mode': 'audio', 'engine': 'whisper', 'thinking': True, 'folder': None}
    job_folder = jobs.jobs_dir(tmp_path) / job['id']
    job_folder.mkdir()
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[3] == 'video_descriptor.speech':
            job['folder'] = 'speech-example'
            result = tmp_path / 'output' / job['folder']
            result.mkdir()
            jobs.write_json(result / 'manifest.json', {'video': str(video)})
            jobs.write_json(result / 'speech.json', {'status': 'done'})
            jobs.write_json(job_folder / 'job.json', job)
        return Mock(returncode=0)

    monkeypatch.setattr(jobs.subprocess, 'run', run)
    jobs.run_job(tmp_path, job_folder, job)
    assert [command[3] for command in commands] == [
        'video_descriptor.speech', 'video_descriptor', 'video_descriptor.translate']
    assert '--audio-only' in commands[1] and '--speech-result' in commands[1]
    assert '--think' in commands[1]
    assert jobs.read_json(job_folder / 'job.json')['status'] == 'done'
    commands.clear()
    jobs.run_job(tmp_path, job_folder, job)
    assert [command[3] for command in commands] == ['video_descriptor', 'video_descriptor.translate']


def test_common_snapshot_shows_speech_before_notes_start(tmp_path, monkeypatch):
    video = tmp_path / 'data' / 'meeting.wav'
    video.parent.mkdir()
    video.touch()
    folder = tmp_path / 'output' / 'speech-example'
    folder.mkdir(parents=True)
    jobs.write_json(folder / 'manifest.json', {'video': str(video), 'mode': 'audio'})
    jobs.write_json(folder / 'speech.json', {'duration': 100, 'processed': 15,
        'message': 'Recognizing speech', 'engine': 'whisper', 'segments': [
            {'start': 0, 'end': 10, 'text': 'Hello', 'speaker': 'speaker_1'}]})
    monkeypatch.setattr(live, 'active_video', lambda video: True)
    snapshot = live.snapshot(tmp_path, folder)
    assert snapshot['phase'] == 2 and snapshot['position'] == 15
    assert snapshot['duration'] == 100 and snapshot['skip_images']
    assert snapshot['skipped_steps'] == [{'phase': 3, 'reason': 'Пропущено для этой записи: анализ изображения отключён.'}]
    assert snapshot['speech'][0]['speaker'] == 'speaker_1'
    assert snapshot['status']['message'] == 'Recognizing speech'


def test_stage_parameters_use_actual_request_and_do_not_leak_to_other_stages():
    payload = {'model': 'actual-model', 'think': False,
               'options': {'temperature': 0.2, 'num_ctx': 32768, 'num_predict': 8000, 'num_gpu': 0}}
    details = live.processing_details(4, {'task': 'фильтрация', 'model': 'stale-model'}, {}, payload)
    parameters = {item['name']: item['value'] for item in details['parameters']}
    assert parameters == {'Модель': 'actual-model', 'Рассуждения': False, **payload['options']}
    assert details['request_available'] and details['supports_thinking']
    assert details['task'] == 'фильтрация'
    diarization = live.processing_details(2, {'model': 'stale-model'}, {
        'stage': 'diarization', 'engine': 'whisper-npu-diarization-xpu',
        'message': 'GPU: segmentation', 'recognition_parameters': {'num_beams': 1}}, payload)
    assert diarization['title'] == 'Распознавание говорящих'
    assert diarization['parameters'] == []
    assert diarization['message'] == 'Для распознавания говорящих параметры не нужны.'
    assert not diarization['request_available'] and not diarization['supports_thinking']
    report = live.processing_details(5, {'model': 'stale-model'}, {}, payload)
    assert report['parameters'] == [] and not report['request_available']
    cached = live.processing_details(4, {'request_state': 'из кэша'}, {})
    assert cached['parameters'] == [] and 'кэша' in cached['message']


def test_speech_and_translation_publish_their_own_parameters():
    speech = live.processing_details(2, {}, {'stage': 'parallel', 'engine': 'whisper-npu-diarization-xpu'},
                                    recognition_settings={'device': 'NPU', 'num_beams': 1})
    assert speech['title'] == 'Распознавание речи и говорящих'
    assert {item['name']: item['value'] for item in speech['parameters']} == {'device': 'NPU', 'num_beams': 1}
    config = {'temperature': 0, 'maxOutputTokens': 4096, 'thinkingConfig': {'thinkingLevel': 'minimal'}}
    translation = live.processing_details(6, {'model': 'gemini-3.5-flash-lite'}, {}, {'generationConfig': config})
    assert {item['name']: item['value'] for item in translation['parameters']} == {
        'Модель': 'gemini-3.5-flash-lite', **config}
    assert not translation['supports_thinking']
