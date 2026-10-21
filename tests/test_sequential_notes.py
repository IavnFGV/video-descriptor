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
