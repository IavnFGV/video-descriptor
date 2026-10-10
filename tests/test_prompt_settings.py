from types import SimpleNamespace

import pytest

from video_descriptor import notes, prompt_settings
from video_descriptor.subtitles import plain_transcript


def test_saved_prompt_is_sent_and_block_snapshot_stays_consistent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured = []
    monkeypatch.setattr(notes, '_chat_json_once', lambda prompt, *args: captured.append(prompt) or '{}')
    prompt_settings.save(tmp_path, {'task': 'summarize', 'text': 'Первый промпт'})
    log = SimpleNamespace(prompt_settings=prompt_settings.overrides(tmp_path))
    prompt_settings.save(tmp_path, {'task': 'summarize', 'text': 'Следующий промпт'})
    notes.chat_json('Стандартный', [], {}, 'model', 'url', log=log, task='summarize')
    notes.chat_json('Стандартный', [], {}, 'model', 'url', task='summarize')
    assert captured == ['Первый промпт', 'Следующий промпт']
    standard = prompt_settings.defaults()['summarize']
    prompt_settings.save(tmp_path, {'task': 'summarize', 'text': standard})
    assert 'summarize' not in prompt_settings.overrides(tmp_path)


@pytest.mark.parametrize('changes', [None, {'task': 'invalid', 'text': 'text'},
                                     {'task': 'summarize', 'text': '  '},
                                     {'task': 'summarize', 'text': 'x' * 50001}])
def test_prompt_validation(tmp_path, changes):
    with pytest.raises(ValueError):
        prompt_settings.save(tmp_path, changes)


def test_plain_transcript_uses_assigned_names_and_timestamps():
    text = plain_transcript({'speaker_names': {'SPEAKER_00': 'Анна'}, 'segments': [
        {'start': 754.5, 'speaker': 'SPEAKER_00', 'text': 'Первая мысль.'},
        {'start': 760, 'speaker': 'SPEAKER_01', 'text': 'Ответ.'},
        {'start': 770, 'speaker': 'unknown', 'text': 'Продолжение.'}]})
    assert text == '[00:12:34] Анна: Первая мысль.\n[00:12:40] SPEAKER_01: Ответ.\n[00:12:50] Продолжение.'
