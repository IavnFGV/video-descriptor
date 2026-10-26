import hashlib
import json
import sys
from unittest.mock import Mock

import pytest

from video_descriptor import construction, jobs, local_tokens, translate
from video_descriptor.models import Source


@pytest.fixture
def vocabulary():
    from tokenizers import Regex, Tokenizer, models, pre_tokenizers, trainers
    tokenizer = Tokenizer(models.BPE())
    tokenizer.pre_tokenizer = pre_tokenizers.Sequence([
        pre_tokenizers.Split(Regex(local_tokens.QWEN35), behavior='isolated'),
        pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False),
    ])
    tokenizer.train_from_iterator([
        'Длинная запись. Объяснение темы и практический пример. Hello world! 12345',
        'Привет! Разбираем обработку видео, перевод и конспект. e\u0301 ё 🙂\n\t',
    ] * 20, trainers.BpeTrainer(vocab_size=600, initial_alphabet=pre_tokenizers.ByteLevel.alphabet()))
    model = json.loads(tokenizer.to_str())['model']
    tokens = [token for token, _ in sorted(model['vocab'].items(), key=lambda row: row[1])]
    info = {'tokenizer.ggml.model': 'gpt2', 'tokenizer.ggml.pre': 'qwen35',
            'tokenizer.ggml.tokens': tokens,
            'tokenizer.ggml.merges': [' '.join(pair) for pair in model['merges']]}
    return tokenizer, info


def test_exported_vocabulary_preserves_token_ids_without_downloads(vocabulary):
    tokenizer, info = vocabulary
    counter = local_tokens.from_metadata(info)
    assert counter.mode == 'model-vocabulary'
    for text in ['Привет! Hello 12345', 'e\u0301 ё 🙂\n\t', '<|im_start|>user', '']:
        assert counter.tokenizer.encode(text).ids == tokenizer.encode(text).ids
        assert counter(text) == len(tokenizer.encode(text).ids) + 256
    text = 'Длинная запись. ' * 3000
    assert counter(text) < local_tokens.byte_bound(text) / 3


@pytest.mark.parametrize('info', [{}, {'tokenizer.ggml.pre': 'unknown'}, {
    'tokenizer.ggml.pre': 'qwen35', 'tokenizer.ggml.model': 'gpt2',
    'tokenizer.ggml.tokens': ['x'], 'tokenizer.ggml.merges': ['bad merge']},
])
def test_unknown_or_invalid_vocabulary_keeps_safe_bound(info):
    counter = local_tokens.from_metadata(info)
    assert counter.mode == 'byte-bound'
    assert counter('Текст') == local_tokens.byte_bound('Текст')


def test_counter_uses_only_selected_show_endpoint(monkeypatch, vocabulary):
    _, info = vocabulary
    response = Mock()
    response.json.return_value = {'model_info': info}
    post = Mock(return_value=response)
    monkeypatch.setattr(local_tokens.requests, 'post', post)
    assert local_tokens.load_counter('http://selected:1234/', 'writer:9b').mode == 'model-vocabulary'
    post.assert_called_once_with('http://selected:1234/api/show',
                                 json={'model': 'writer:9b', 'verbose': True}, timeout=(5, 30))
    response.close.assert_called_once()


def test_normalization_is_selected_by_metadata(vocabulary):
    from tokenizers import normalizers
    tokenizer, info = vocabulary
    tokenizer.normalizer = normalizers.NFC()
    counter = local_tokens.from_metadata({**info, 'tokenizer.ggml.normalizer.nfc': True})
    text = 'e\u0301 ё 🙂'
    assert counter.tokenizer.encode(text).ids == tokenizer.encode(text).ids


def test_token_splitting_also_preserves_explicit_character_limit(vocabulary):
    counter = local_tokens.from_metadata(vocabulary[1])
    text = 'Длинная запись ' * 1000
    parts = construction.split_text(text, 2000, counter, char_limit=1000)
    assert len(parts) > 1
    assert all(len(part) <= 1000 and counter(part) <= 2000 for part in parts)
    assert ' '.join(parts).split() == text.split()


def test_chunked_local_notes_do_not_allocate_model_maximum(tmp_path, monkeypatch, vocabulary):
    counter = local_tokens.from_metadata(vocabulary[1])
    folder = tmp_path / 'output/chunks'
    folder.mkdir(parents=True)
    jobs.write_json(folder / 'speech.json', {'status': 'done', 'segments': [
        {'id': f's{i}', 'start': i * 400, 'end': i * 400 + 10, 'speaker': 'unknown',
         'text': 'Объяснение темы и практический пример. ' * 100} for i in range(3)]})
    jobs.write_json(folder / 'manifest.json', {'video': str(tmp_path / 'video.mp4')})
    monkeypatch.setattr(construction, 'render', lambda *a, **kw: None)
    monkeypatch.setattr(construction, 'actual_limits', lambda root, config: {**config, 'context_tokens': 262144})
    monkeypatch.setattr(construction, 'load_counter', lambda *a: counter)
    contexts = []

    def chat(prompt, text, schema, model, base, log, **kwargs):
        contexts.append(kwargs['context'])
        assert counter(text) + counter(prompt) + 2048 + 1024 <= kwargs['context']
        return '## Оглавление\n### [00:00:00] Тема\n\n## Конспект\n### [00:00:00] Тема\nОбъяснение.'

    monkeypatch.setattr('video_descriptor.notes.chat_json', chat)
    construction.run(tmp_path, folder, {'strategy': 'chunks', 'auto_context': True, 'output_tokens': 2048})
    assert len(contexts) == 4  # Three parts plus consolidation.
    assert max(contexts) < 16384


def test_long_local_notes_use_one_request_and_small_context(tmp_path, monkeypatch, vocabulary):
    counter = local_tokens.from_metadata(vocabulary[1])
    folder = tmp_path / 'output/notes'
    folder.mkdir(parents=True)
    jobs.write_json(folder / 'speech.json', {'status': 'done', 'segments': [
        {'id': 's1', 'start': 0, 'end': 7200, 'speaker': 'unknown',
         'text': 'Длинная запись. ' * 3000}]})
    jobs.write_json(folder / 'manifest.json', {'video': str(tmp_path / 'video.mp4')})
    monkeypatch.setattr(construction, 'render', lambda *a, **kw: None)
    monkeypatch.setattr(construction, 'actual_limits', lambda root, config: {**config, 'context_tokens': 65536})
    monkeypatch.setattr(construction, 'load_counter', lambda *a: counter)
    calls = []

    def chat(prompt, text, schema, model, base, log, **kwargs):
        calls.append(kwargs)
        assert counter(text) + counter(prompt) + 2048 + 1024 <= kwargs['context']
        return '## Оглавление\n### [00:00:00] Тема\n\n## Конспект\n### [00:00:00] Тема\nОбъяснение.'

    monkeypatch.setattr('video_descriptor.notes.chat_json', chat)
    construction.run(tmp_path, folder, {'auto_context': True, 'output_tokens': 2048})
    plan = jobs.read_json(folder / 'construction-plan.json')
    assert plan['strategy'] == 'whole' and len(calls) == 1
    assert plan['input_upper_bound'] > plan['context_tokens']
    assert plan['token_counting'] == 'model-vocabulary'
    assert plan['effective_context_tokens'] < plan['input_upper_bound']
    assert calls[0]['context'] == plan['effective_context_tokens']


def test_sparse_two_hour_translation_is_packed_by_text(vocabulary):
    counter = local_tokens.from_metadata(vocabulary[1])
    sources = [Source(id=f's{i}', start=i * 60, end=i * 60 + 10,
                      text='Привет! Hello world!') for i in range(120)]
    groups = translate.translation_groups(sources, counter)
    assert len(groups) < 10  # Old 90-second grouping needs 80 requests.
    assert [source.id for group in groups for source in group] == [source.id for source in sources]
    for group in groups:
        text = '\n\n'.join(f'[[s{i:04d}]]\n{source.text}' for i, source in enumerate(group, 1))
        assert counter(text) <= 1256
    assert len(translate.translation_groups(sources, local_tokens.TokenCounter())) == 80


@pytest.mark.parametrize('cached', [False, True])
def test_partial_translation_resume_sends_only_missing_replicas(tmp_path, monkeypatch, cached):
    sources = [Source(id=f's{i}', start=i * 10, end=i * 10 + 5, text='Hello') for i in range(3)]
    jobs.write_json(tmp_path / 'transcript.json', [source.model_dump() for source in sources])
    jobs.write_json(tmp_path / 'translations.json', {'s0': 'Сохранено', 's2': ''})
    monkeypatch.setattr(sys, 'argv', ['translate', str(tmp_path), '--model', 'selected'])
    monkeypatch.setattr(translate, 'load_counter', lambda *a: local_tokens.TokenCounter())
    monkeypatch.setattr(translate, 'translation_settings', lambda: {'provider': 'ollama'})
    monkeypatch.setattr(translate, 'refresh_reports', lambda *a: None)
    if cached:
        key = hashlib.sha256(json.dumps(
            [translate.PROMPT, 'selected', 'http://host.docker.internal:11434',
             [source.model_dump() for source in sources]], sort_keys=True,
        ).encode()).hexdigest()[:12]
        jobs.write_json(tmp_path / f'translation-{key}.json', {
            's0': 'Старый перевод', 's1': 'Новый перевод', 's2': 'Был объединён'})
    seen = []

    def generate(sources, *a):
        seen.extend(source.id for source in sources)
        return {'s1': 'Новый перевод'}

    monkeypatch.setattr(translate, 'translate_resilient', generate)
    assert translate.main() == 0
    assert seen == ([] if cached else ['s1'])
    assert jobs.read_json(tmp_path / 'translations.json') == {
        's0': 'Сохранено', 's1': 'Новый перевод', 's2': ''}
