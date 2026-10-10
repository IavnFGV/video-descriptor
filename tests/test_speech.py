import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer

import pytest
import requests

from video_descriptor import speech
from video_descriptor.jobs import enqueue
from video_descriptor.serve import RangeRequestHandler


def test_edit_split_preserves_source_and_requires_valid_boundary_and_revision(tmp_path):
    folder = tmp_path / 'output/speech-test'
    folder.mkdir(parents=True)
    original = {'status': 'done', 'folder': 'speech-test', 'segments': [
        {'start': 10.25, 'end': 20.75, 'text': 'Вопрос? Ответ.', 'speaker': 'SPEAKER_00'},
        {'start': 21, 'end': 25, 'text': 'Дальше.', 'speaker': 'SPEAKER_01'}]}
    speech.write_json(folder / 'speech.json', original)
    revision = speech.state(tmp_path, {'folder': ['speech-test']})['result']['edit_revision']
    payload = {'folder': 'speech-test', 'revision': revision, 'index': 0, 'action': 'split',
               'at': 15.5, 'text': 'Вопрос?', 'speaker': 'SPEAKER_00',
               'right_text': 'Исправленный ответ.', 'right_speaker': 'SPEAKER_01'}
    for at in [10.25, 20.75, 100, float('nan'), True]:
        with pytest.raises(ValueError, match='Время разделения'):
            speech.edit_utterance(tmp_path, {**payload, 'at': at})
    saved = speech.edit_utterance(tmp_path, payload)
    assert [(s['start'], s['end'], s['speaker']) for s in saved['segments'][:2]] == [
        (10.25, 15.5, 'SPEAKER_00'), (15.5, 20.75, 'SPEAKER_01')]
    assert saved['segments'][2] == original['segments'][1]
    assert speech.read_json(folder / 'speech.json') == original
    with pytest.raises(ValueError, match='изменились'):
        speech.edit_utterance(tmp_path, payload)
    updated = speech.edit_utterance(tmp_path, {**payload, 'revision': saved['edit_revision'],
                                              'index': 1, 'action': 'edit', 'text': 'Да.',
                                              'speaker': 'SPEAKER_00'})
    assert updated['segments'][1] == {
        'start': 15.5, 'end': 20.75, 'speaker': 'SPEAKER_00', 'text': 'Да.'}
    assert speech.state(tmp_path, {'folder': ['speech-test']})['result'] == updated


def test_recovery_status_shows_current_text_and_keeps_gpu_progress(tmp_path):
    job_id = 'a' * 32
    job_file = tmp_path / 'output/jobs' / job_id / 'job.json'
    result_folder = tmp_path / 'output/speech-test'
    job_file.parent.mkdir(parents=True)
    result_folder.mkdir(parents=True)
    speech.write_json(job_file, {'mode': 'audio', 'folder': 'speech-test',
                                'status': 'running', 'started': 123})
    original = {'processed': 3300, 'segments': [], 'parallel': {'diarization': 'embeddings 50%'}}
    speech.write_json(result_folder / 'speech.json', original)
    speech.write_json(result_folder / 'npu-recovery.json', {
        'job_started': 123, 'status': 'running', 'processed': 4200,
        'segments': [{'text': 'Новый текст'}], 'message': 'VAD → NPU'})
    result = speech.state(tmp_path, {'job': [job_id]})['result']
    assert result['processed'] == 4200
    assert result['segments'][0]['text'] == 'Новый текст'
    assert 'embeddings 50%' in result['message']
    assert speech.read_json(result_folder / 'speech.json') == original
    job = speech.read_json(job_file)
    speech.write_json(job_file, {**job, 'started': 456})
    assert speech.state(tmp_path, {'job': [job_id]})['result'] == original


def test_source_escape_and_engine_validation(tmp_path):
    (tmp_path / 'data').mkdir()
    outside = tmp_path / 'secret.wav'
    outside.write_bytes(b'audio')
    with pytest.raises(ValueError):
        speech.enqueue_existing(tmp_path, str(outside), 'whisper')
    inside = tmp_path / 'data' / 'meeting.wav'
    inside.write_bytes(b'audio')
    with pytest.raises(ValueError):
        speech.enqueue_existing(tmp_path, str(inside), 'other')
    first = speech.enqueue_existing(tmp_path, str(inside), 'whisper')
    second = speech.enqueue_existing(tmp_path, str(inside), 'whisper')
    assert first['id'] != second['id']
    assert first['mode'] == 'audio'


def test_audio_upload_and_speaker_turns(tmp_path):
    import io
    j = enqueue(tmp_path, io.BytesIO(b'audio'), 5, 'meeting.wav', mode='audio', engine='whisper')
    assert j['mode'] == 'audio'
    assert speech.group_words([
        {'start': 0, 'end': 1, 'speaker': 'a', 'text': 'Hello'},
        {'start': 1, 'end': 2, 'speaker': 'a', 'text': 'world'},
        {'start': 2, 'end': 3, 'speaker': 'b', 'text': 'Yes'},
    ]) == [
        {'start': 0, 'end': 2, 'speaker': 'a', 'text': 'Hello world'},
        {'start': 2, 'end': 3, 'speaker': 'b', 'text': 'Yes'},
    ]


def test_speech_view_names_and_no_cross_origin_write(tmp_path):
    folder = tmp_path / 'output' / 'speech-example'
    folder.mkdir(parents=True)
    data = {'status': 'done', 'speaker_names': {}, 'segments': []}
    (folder / 'speech.json').write_text(json.dumps(data))
    http = ThreadingHTTPServer(('127.0.0.1', 0), partial(RangeRequestHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{http.server_port}'
    try:
        response = requests.get(base + '/speech?job=' + 'a' * 32, timeout=5)
        assert response.status_code == 200
        assert response.url == base + '/create?job=' + 'a' * 32
        assert 'id="speech-feed"' in response.text
        assert 'id="speaker-names-form"' in response.text
        assert requests.get(base + '/studio-assets/create.js', timeout=5).status_code == 200
        payload = {'folder': folder.name, 'speaker_names': {'spk:0': 'Alice'}}
        assert requests.post(base + '/api/speech-names', json=payload, timeout=5).status_code == 200
        r = requests.get(base + '/api/speech?folder=' + folder.name, timeout=5)
        assert r.json()['result']['speaker_names']['spk:0'] == 'Alice'
        assert requests.post(base + '/api/speech-names', json=payload,
                             headers={'Origin': 'http://elsewhere'}, timeout=5).status_code == 403
        assert requests.post(base + '/api/speech-names', json={**payload, 'folder': '../escape'},
                             timeout=5).status_code == 400
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


def test_audio_pipeline_cached_google_response_skips_api(tmp_path, monkeypatch):
    import wave
    data = tmp_path / 'data'
    data.mkdir()
    video = data / 'meeting.wav'
    with wave.open(str(video), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\0\0' * 16000)
    monkeypatch.setattr(speech, 'load', lambda root: {'api_key': 'secret', 'billing_mode': 'paid'})
    j = speech.enqueue_existing(tmp_path, str(video), 'gemini')
    folder = tmp_path / 'output' / ('speech-' + j['id'])
    chunk = folder / 'chunk-0001'
    chunk.mkdir(parents=True)
    response = {'steps': [{'content': [{'annotations': [
        {'type': 'word_info', 'start_offset': '0s', 'end_offset': '0.9s',
         'speaker': 'spk:0', 'text': 'Привет'},
    ]}]}]}
    (chunk / 'response.json').write_text(json.dumps(response))
    monkeypatch.setattr(speech, 'google_chunk', lambda *args: pytest.fail('Cached request resent'))
    speech.run(tmp_path, tmp_path / 'output' / 'jobs' / j['id'], j)
    result = json.loads((folder / 'speech.json').read_text())
    assert result['status'] == 'done'
    assert result['segments'][0]['text'] == 'Привет'
    # Recognition is an intermediate stage; the common pipeline creates the report.
    assert not (folder / 'report.html').exists()
    assert not (folder / 'notes.json').exists()
    assert not (folder / 'frames.json').exists()


def test_hybrid_keeps_google_text_and_assigns_global_gpu_speakers(tmp_path, monkeypatch):
    import wave
    data = tmp_path / 'data'
    data.mkdir()
    video = data / 'meeting.wav'
    with wave.open(str(video), 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\0\0' * 16000)
    monkeypatch.setattr(speech, 'load', lambda root: {'api_key': 'secret', 'billing_mode': 'paid'})
    j = speech.enqueue_existing(tmp_path, str(video), 'gemini-diarization-xpu')
    calls = []

    def google(audio, folder, key, *, diarization):
        assert diarization is False
        response = {'steps': [{'content': [{'annotations': [
            {'type': 'word_info', 'start_offset': '0s', 'end_offset': '0.4s', 'text': 'Привет'},
            {'type': 'word_info', 'start_offset': '0.5s', 'end_offset': '0.9s', 'text': 'Да'},
        ]}]}]}
        speech.write_json(folder / 'response.json', response)
        calls.append('google')
        return response

    def diarize(root, audio, folder, device, update):
        assert device == 'xpu'
        calls.append('gpu')
        if calls.count('gpu') == 1:
            raise RuntimeError('Interrupted diarization')
        return [{'start': 0, 'end': 0.4, 'speaker': 'SPEAKER_00'},
                {'start': 0.5, 'end': 1, 'speaker': 'SPEAKER_01'}]

    monkeypatch.setattr(speech, 'google_chunk', google)
    monkeypatch.setattr(speech, 'diarize', diarize)
    job_folder = tmp_path / 'output' / 'jobs' / j['id']
    with pytest.raises(RuntimeError, match='Interrupted'):
        speech.run(tmp_path, job_folder, j)
    speech.run(tmp_path, job_folder, j)
    result = speech.read_json(tmp_path / 'output' / j['folder'] / 'speech.json')
    assert calls == ['google', 'gpu', 'gpu']
    assert result['status'] == 'done'
    assert [s['speaker'] for s in result['segments']] == ['SPEAKER_00', 'SPEAKER_01']
    assert [s['text'] for s in result['segments']] == ['Привет', 'Да']


def test_npu_and_gpu_actually_overlap_and_merge_after_both_finish(tmp_path, monkeypatch):
    import wave

    from video_descriptor import speech_npu
    data = tmp_path / 'data'
    data.mkdir()
    video = data / 'meeting.wav'
    with wave.open(str(video), 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\0\0' * 16000)
    monkeypatch.setattr(speech_npu, 'health', dict)
    job = speech.enqueue_existing(tmp_path, str(video), 'whisper-npu-diarization-xpu')
    gpu_started, npu_finished = threading.Event(), threading.Event()

    def diarize(root, audio, folder, device, update):
        assert device == 'xpu'
        gpu_started.set()
        assert npu_finished.wait(timeout=3), 'NPU was not started while GPU was running'
        update('GPU завершён')
        return [{'start': 0, 'end': 1, 'speaker': 'SPEAKER_00'}]

    def transcribe(audio, folder, on_chunk, log):
        assert gpu_started.wait(timeout=3), 'GPU did not start before NPU finished'
        items = [{'start': 0, 'end': .9, 'text': 'Привет', 'speaker': 'Без разметки'}]
        on_chunk(items, 1)
        npu_finished.set()
        return items, 'word'

    monkeypatch.setattr(speech, 'diarize', diarize)
    monkeypatch.setattr(speech_npu, 'transcribe', transcribe)
    speech.run(tmp_path, tmp_path / 'output/jobs' / job['id'], job)
    result = speech.read_json(tmp_path / 'output' / job['folder'] / 'speech.json')
    assert result['status'] == 'done'
    assert result['segments'][0]['speaker'] == 'SPEAKER_00'
    assert result['parallel']['diarization'] == 'готово'
