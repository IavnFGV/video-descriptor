from video_descriptor import construction, jobs


def test_chunk_memory_progress_and_cached_resume(tmp_path, monkeypatch):
    folder = tmp_path / 'output/notes'
    folder.mkdir(parents=True)
    rows = [{'id': str(i), 'start': i * 40, 'end': i * 40 + 20, 'text': 'Material ' + str(i), 'speaker': 'speaker_1'} for i in range(3)]
    jobs.write_json(folder / 'speech.json', {'status': 'done', 'segments': rows, 'translations': {}})
    jobs.write_json(folder / 'manifest.json', {'video': str(tmp_path / 'video.mp4')})
    monkeypatch.setattr(construction, 'render', lambda *a, **kw: None)
    calls = []
    answer = '## Оглавление\n### [00:00:00] Topic\n\n## Конспект\n### [00:00:00] Topic\nRemember this fact.\n'

    def ask(root, config, text, log, stage='Конспект'):
        calls.append((text, stage, log.snapshot()))
        assert construction.input_bound(text) + construction.input_bound(config['prompt']) + config['output_tokens'] + 1024 <= config['context_tokens']
        return answer

    config = {'strategy': 'chunks', 'grouping': 'time', 'chunk_seconds': 30}
    construction.run(tmp_path, folder, config, ask=ask)
    chunks = [row for row in calls if row[1] == 'Конспект']
    assert len(chunks) == 3
    assert 'Память предыдущих частей' not in chunks[0][0]
    assert 'Remember this fact.' in chunks[1][0]
    assert chunks[2][2]['completed'] == 2 and chunks[2][2]['total'] == 3
    assert any(row[2]['phase'] == 'consolidation' for row in calls)
    calls.clear()
    construction.run(tmp_path, folder, config, ask=ask)
    assert not any(row[1] == 'Конспект' for row in calls)
    assert jobs.read_json(folder / 'progress.json')['request_state'] == 'готово'


def test_large_google_context_uses_exact_count_and_one_generation(tmp_path, monkeypatch):
    from video_descriptor import gemini
    folder = tmp_path / 'output/large'
    folder.mkdir(parents=True)
    text = 'Длинная расшифровка. ' * 12000
    rows = [{'id': 's1', 'start': 0, 'end': 600, 'text': text, 'speaker': 'unknown'}]
    jobs.write_json(folder / 'speech.json', {'status': 'done', 'segments': rows, 'translations': {}})
    jobs.write_json(folder / 'manifest.json', {'video': str(tmp_path / 'video.mp4')})
    monkeypatch.setattr(construction, 'render', lambda *a, **kw: None)
    monkeypatch.setattr(construction, 'credentials', lambda root: {'api_key': 'private', 'billing_mode': 'paid'})
    calls = []
    answer = '## Оглавление\n### [00:00:00] Topic\n\n## Конспект\n### [00:00:00] Topic\nSummary.\n'

    def call(method, url, key, **kwargs):
        calls.append((method, url, kwargs))
        if method == 'GET':
            return {'inputTokenLimit': 65536, 'outputTokenLimit': 4096}
        if url.endswith(':countTokens'):
            assert text in kwargs['json']['generateContentRequest']['contents'][0]['parts'][0]['text']
            return {'totalTokens': 30000}
        assert url.endswith(':generateContent')
        assert text in kwargs['json']['contents'][0]['parts'][0]['text']
        return {'candidates': [{'content': {'parts': [{'text': answer}]}, 'finishReason': 'STOP'}]}

    monkeypatch.setattr(gemini, 'call', call)
    construction.run(tmp_path, folder, {'provider': 'gemini', 'model': 'gemini-test', 'auto_context': True,
                                        'context_tokens': 16384, 'output_tokens': 2048})
    plan = jobs.read_json(folder / 'construction-plan.json')
    assert plan['context_tokens'] == 65536
    assert plan['input_upper_bound'] > 65536  # Byte estimate would wrongly split the text.
    assert plan['input_tokens'] == 30000
    assert plan['strategy'] == 'whole' and plan['blocks'] == plan['generation_requests'] == 1
    assert sum(url.endswith(':generateContent') for _, url, _ in calls) == 1
    assert sum(url.endswith(':countTokens') for _, url, _ in calls) == 1
    assert not list(folder.glob('construction-merge-*'))


def test_manual_context_is_preserved_and_oversize_google_text_splits(tmp_path, monkeypatch):
    from video_descriptor import gemini
    folder = tmp_path / 'output/manual'
    folder.mkdir(parents=True)
    jobs.write_json(folder / 'speech.json', {'status': 'done', 'segments': [
        {'id': 's1', 'start': 0, 'end': 600, 'text': 'Some text. ' * 4000, 'speaker': 'unknown'}]})
    monkeypatch.setattr(construction, 'credentials', lambda root: {'api_key': 'private', 'billing_mode': 'paid'})
    monkeypatch.setattr(gemini, 'call', lambda method, *a, **kw: {'inputTokenLimit': 1000000, 'outputTokenLimit': 4096} if method == 'GET' else {'totalTokens': 30000})
    config = construction.actual_limits(tmp_path, construction.validate({'provider': 'gemini', 'model': 'gemini-test',
                                                                        'context_tokens': 16384, 'output_tokens': 2048}))
    assert not config['auto_context'] and config['context_tokens'] == 16384
    result, blocks = construction.plan(folder, config, root=tmp_path)
    assert result['strategy'] == 'chunks' and len(blocks) > 1
