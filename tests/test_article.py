import hashlib
import json
from unittest.mock import Mock

import pytest

from video_descriptor import construction, jobs, postprocess, recording


@pytest.fixture
def lecture(tmp_path):
    video = tmp_path / 'data/lecture.mp4'
    video.parent.mkdir()
    video.write_bytes(b'fixture')
    folder = tmp_path / 'output/original'
    folder.mkdir(parents=True)
    rows = [{'id': 's1', 'start': 0, 'end': 20, 'speaker': 'unknown', 'text': 'First idea'},
            {'id': 's2', 'start': 20, 'end': 40, 'speaker': 'unknown', 'text': 'Final conclusion'}]
    jobs.write_json(folder / 'manifest.json', {'video': str(video)})
    jobs.write_json(folder / 'speech.json', {'status': 'done', 'segments': rows})
    jobs.write_json(folder / 'transcript-edits.json', {'segments': [{**rows[0], 'text': 'Corrected first idea'}, rows[1]]})
    (folder / 'notes.user.md').write_text('Existing notes', encoding='utf-8')
    return tmp_path, folder


def test_article_is_one_full_corrected_transcript_request_and_independent_result(lecture):
    root, source = lecture
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    job = postprocess.enqueue(root, source.name, 'notes', 'chosen:9b', 'http://127.0.0.1:11434',
                              construction={'result_kind': 'article', 'model': 'chosen:9b'}, translate_after=True)
    assert job['translate_after'] is False
    assert job['title'].startswith('Статья')
    folder = root / 'output' / job['folder']
    calls = []
    answer = '# Article\n\n## First idea\n\nA connected explanation.\n\n## Conclusion\n\nThe result.'

    def ask(root, config, text, log):
        calls.append(text)
        assert config['prompt'] == construction.ARTICLE_PROMPT
        assert config['strategy'] == 'whole'
        return answer

    construction.run(root, folder, job['construction'], ask=ask)
    assert len(calls) == 1
    assert 'Corrected first idea' in calls[0] and 'Final conclusion' in calls[0]
    assert 'Existing notes' not in calls[0]
    assert (folder / 'article.md').read_text(encoding='utf-8') == answer
    assert (folder / 'editor-default.md').read_text(encoding='utf-8') == answer
    assert 'data-result-kind="article"' in (folder / 'report.html').read_text(encoding='utf-8')
    assert jobs.read_json(folder / 'construction-plan.json')['generation_requests'] == 1
    assert jobs.read_json(folder / 'progress.json')['message'] == 'Статья сохранена'
    assert recording.variants(root, folder=source.name)['reports'][0]['result_kind'] == 'article'
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}
    construction.run(root, folder, job['construction'], ask=ask)
    assert len(calls) == 1  # Exact saved response resumes without another generation.


def test_article_cannot_silently_split_or_use_slides_or_notes_prompt(lecture, monkeypatch):
    root, folder = lecture
    settings = construction.validate({'result_kind': 'article', 'strategy': 'chunks', 'input': 'slides', 'prompt': 'Summarize'})
    assert settings['strategy'] == 'whole' and settings['input'] == 'speech'
    assert settings['prompt'] == construction.ARTICLE_PROMPT
    config = {**settings, 'context_tokens': 8192, 'output_tokens': 512}
    rows = jobs.read_json(folder / 'speech.json')['segments']
    rows[0]['text'] = 'Huge lecture. ' * 5000
    jobs.write_json(folder / 'speech.json', {'status': 'done', 'segments': rows})
    (folder / 'transcript-edits.json').unlink()
    ask = Mock()
    monkeypatch.setattr(construction, 'group_material', Mock(side_effect=AssertionError('Must not chunk')))
    with pytest.raises(ValueError, match='по частям пока не поддерживается'):
        construction.run(root, folder, config, ask=ask)
    ask.assert_not_called()
    assert not (folder / 'report.html').exists()


def test_article_worker_does_not_start_subtitle_translation(lecture, monkeypatch):
    root, source = lecture
    job = postprocess.enqueue(root, source.name, 'notes', 'chosen:9b', 'http://127.0.0.1:11434',
                              construction={'result_kind': 'article'})
    calls = []
    monkeypatch.setattr(postprocess, 'run_process', lambda folder, command, **kw: calls.append(command) or Mock(returncode=0))
    jobs.run_job(root, root / 'output/jobs' / job['id'], job)
    assert len(calls) == 1 and calls[0][3] == 'video_descriptor.construction'
    assert job['status'] == 'done'


def test_google_article_uses_one_generation_and_accepts_headings_without_timecodes(lecture, monkeypatch):
    from video_descriptor import gemini
    root, source = lecture
    folder = root / 'output/article'
    folder.mkdir()
    for name in ('manifest.json', 'speech.json', 'transcript-edits.json'):
        (folder / name).write_bytes((source / name).read_bytes())
    monkeypatch.setattr(construction, 'credentials', lambda root: {'api_key': 'fixture', 'billing_mode': 'paid'})
    calls = []

    def call(method, url, key, **kwargs):
        calls.append(url)
        if method == 'GET':
            return {'inputTokenLimit': 32768, 'outputTokenLimit': 4096}
        if url.endswith(':countTokens'):
            return {'totalTokens': 2000}
        payload = kwargs['json']
        assert payload['systemInstruction']['parts'][0]['text'] == construction.ARTICLE_PROMPT
        assert 'Corrected first idea' in payload['contents'][0]['parts'][0]['text']
        assert 'Final conclusion' in payload['contents'][0]['parts'][0]['text']
        return {'candidates': [{'content': {'parts': [{'text': '# Статья\n\n## Тема\n\nСвязное изложение.'}]},
                                'finishReason': 'STOP'}]}

    monkeypatch.setattr(gemini, 'call', call)
    construction.run(root, folder, {'result_kind': 'article', 'provider': 'gemini', 'model': 'gemini-test'})
    assert sum(url.endswith(':generateContent') for url in calls) == 1
    assert sum(url.endswith(':countTokens') for url in calls) == 1
    assert (folder / 'article.md').read_text(encoding='utf-8').startswith('# Статья')


def test_article_feature_preserves_existing_notes_response_cache(lecture):
    root, folder = lecture
    config = construction.validate({'auto_context': False})
    _, blocks = construction.plan(folder, config)
    legacy = {key: value for key, value in config.items() if key != 'result_kind'}
    digest = hashlib.sha256(json.dumps([legacy, blocks[0], '', 'sequential-context-v1'], sort_keys=True).encode()).hexdigest()[:16]
    answer = '## Оглавление\n### [00:00:00] Тема\nОписание\n## Конспект\n### [00:00:00] Тема\nОбъяснение'
    (folder / f'construction-part-{digest}.md').write_text(answer, encoding='utf-8')
    ask = Mock(side_effect=AssertionError('Existing notes response must be reused'))
    construction.run(root, folder, config, ask=ask)
    ask.assert_not_called()
    assert (folder / 'notes.md').read_text(encoding='utf-8') == answer


def test_article_custom_prompt_is_independent_and_validated():
    config = construction.validate({'result_kind': 'article', 'prompt': 'Notes only',
                                    'article_prompt': 'Write an accessible article'})
    assert config['prompt'] == 'Write an accessible article'
    assert construction.validate({'prompt': 'Notes only', 'article_prompt': 'Article only'})['prompt'] == 'Notes only'
    assert construction.validate(config)['prompt'] == 'Write an accessible article'
    with pytest.raises(ValueError, match='Промпт статьи'):
        construction.validate({'article_prompt': ' '})
