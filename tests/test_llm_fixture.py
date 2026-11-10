"""Real adapter HTTP exchanges against a deterministic external-boundary fixture."""
import importlib.util
from pathlib import Path

import pytest
import requests

from video_descriptor.construction import PROMPTS, parsed_notes
from video_descriptor.models import Source
from video_descriptor.notes import chat_json
from video_descriptor.translate import translate_batch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('test_llm_boundary', ROOT / 'windows-app/sandbox/llm_fixture.py')
fixture_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_module)


def test_fixture_exercises_real_streaming_translation_and_notes_contracts():
    with fixture_module.LLMFixture() as fixture:
        sources = [Source(id='one', start=62, end=65, text='A synthetic sentence.'),
                   Source(id='two', start=65, end=69, text='A second sentence.')]
        translations = translate_batch(sources, fixture_module.MODEL, fixture.url)
        assert set(translations) == {'one', 'two'} and all(translations.values())
        answer = chat_json(PROMPTS['lecture'], '[00:01:02] Speaker: A synthetic sentence.',
                           None, fixture_module.MODEL, fixture.url, task='construction')
        notes, chapters = parsed_notes(answer, sources)
        assert notes.notes and chapters[0].start == 62
        assert {e.get('task') for e in fixture.events} == {'translation', 'notes'}
        assert 'synthetic' not in str(fixture.evidence())  # No request bodies in evidence.


def test_fixture_invalid_answer_is_rejected_by_production_parser():
    with fixture_module.LLMFixture() as fixture:
        fixture.mode = 'invalid-notes'
        answer = chat_json(PROMPTS['lecture'], '[00:00:00] Speaker: Test.', None,
                           fixture_module.MODEL, fixture.url, task='construction')
        with pytest.raises(ValueError, match='разделов'):
            parsed_notes(answer, [Source(id='one', start=0, end=3, text='Test.')])


def test_fixture_truncated_stream_is_never_a_success(monkeypatch):
    from video_descriptor import notes
    monkeypatch.setattr(notes.time, 'sleep', lambda _: None)
    with fixture_module.LLMFixture() as fixture:
        fixture.mode = 'truncated'
        with pytest.raises(RuntimeError, match='поток ответа оборвался'):
            chat_json(PROMPTS['lecture'], '[00:00:00] Speaker: Test.', None,
                      fixture_module.MODEL, fixture.url, task='construction')
        assert len([e for e in fixture.events if e['route'] == '/api/chat']) == 3


def test_fixture_rejects_incorrect_wire_protocol_and_unknown_model():
    with fixture_module.LLMFixture() as fixture:
        assert requests.post(fixture.url + '/api/chat', json={'model': 'unexpected'}, timeout=5).status_code == 400
        assert requests.post(fixture.url + '/api/chat', json={'model': fixture_module.MODEL,
                             'messages': [], 'stream': False}, timeout=5).status_code == 400


@pytest.mark.parametrize('kind,mode', [('notes', 'valid'), ('article', 'valid'), ('notes', 'invalid-notes')])
def test_real_construction_pipeline_saves_or_rejects_http_fixture(tmp_path, monkeypatch, kind, mode):
    from video_descriptor import construction, jobs
    monkeypatch.setenv('VIDEO_DESCRIPTOR_EVENTS', str(tmp_path / 'events.jsonl'))
    folder = tmp_path / 'output/synthetic'
    folder.mkdir(parents=True)
    video = tmp_path / 'sample.mp4'
    video.write_bytes(b'synthetic visual fixture; no media inference claim')
    jobs.write_json(folder / 'manifest.json', {'video': str(video)})
    jobs.write_json(folder / 'speech.json', {'status': 'done', 'segments': [
        {'id': 's1', 'start': 0, 'end': 9, 'text': 'A local transcription test.', 'speaker': 'unknown'}]})
    with fixture_module.LLMFixture() as fixture:
        fixture.mode = mode
        monkeypatch.setenv('VIDEO_DESCRIPTOR_JOB_OLLAMA_URL', fixture.url)
        config = {'model': fixture_module.MODEL, 'result_kind': kind}
        if mode == 'invalid-notes':
            with pytest.raises(ValueError, match='разделов'):
                construction.run(tmp_path, folder, config)
            assert (folder / 'construction-result.md').is_file()
            assert not (folder / 'report.html').exists()
        else:
            construction.run(tmp_path, folder, config)
            assert (folder / 'report.html').is_file()
            assert (folder / ('article.md' if kind == 'article' else 'notes.md')).is_file()
        assert any(e.get('task') == kind for e in fixture.events)
