import copy

import pytest

from video_descriptor.jobs import write_json
from video_descriptor.speech import edit_utterance, editable_result, subtitle_result


@pytest.fixture
def history(tmp_path):
    folder = tmp_path / 'output' / 'speech'
    folder.mkdir(parents=True)
    rows = [{'id': 'a', 'start': 0, 'end': 10, 'text': 'First second', 'speaker': 'one'},
            {'id': 'b', 'start': 10, 'end': 20, 'text': 'Next', 'speaker': 'unknown'}]
    write_json(folder / 'speech.json', {'status': 'done', 'duration': 20, 'segments': rows})
    write_json(folder / 'transcript.json', rows)
    write_json(folder / 'translations.json', {'a': 'Первая вторая', 'b': 'Далее'})
    return tmp_path, folder, editable_result(folder, subtitle_result(folder))


def restore(root, before, revision):
    return edit_utterance(root, {'folder': 'speech', 'revision': revision, 'action': 'restore',
                                 'segments': before['segments'], 'translations': before['translations']})


def test_undo_redo_split_restores_ids_timing_speakers_and_translation(history):
    root, _, initial = history
    split = edit_utterance(root, {'folder': 'speech', 'revision': initial['edit_revision'], 'index': 0,
                                 'action': 'split', 'text': 'First', 'speaker': 'one', 'at': 5,
                                 'right_text': 'second', 'right_speaker': 'unknown',
                                 'translation': 'Первая', 'right_translation': 'вторая'})
    undone = restore(root, initial, split['edit_revision'])
    assert undone['segments'] == initial['segments']
    assert undone['translations'] == initial['translations']
    assert undone['edit_revision'] == initial['edit_revision']
    redone = restore(root, split, undone['edit_revision'])
    assert redone['segments'] == split['segments']
    assert redone['translations'] == split['translations']


def test_undo_conflict_never_overwrites_later_change(history):
    root, folder, initial = history
    changed = edit_utterance(root, {'folder': 'speech', 'revision': initial['edit_revision'], 'index': 0,
                                   'action': 'edit', 'text': 'Another editor', 'speaker': 'one'})
    before = (folder / 'transcript-edits.json').read_bytes()
    with pytest.raises(ValueError, match='изменились'):
        restore(root, initial, initial['edit_revision'])
    assert before == (folder / 'transcript-edits.json').read_bytes()
    assert changed['segments'][0]['text'] == 'Another editor'


def test_undo_preserves_genuine_unknown_end_without_inventing_time(history):
    root, folder, _ = history
    raw = subtitle_result(folder)
    raw['segments'][1]['end'] = -1
    write_json(folder / 'speech.json', raw)
    write_json(folder / 'transcript.json', raw['segments'])
    initial = editable_result(folder, raw)
    changed = edit_utterance(root, {'folder': 'speech', 'revision': initial['edit_revision'], 'index': 0,
                                   'action': 'edit', 'text': 'Changed', 'speaker': 'one'})
    undone = restore(root, initial, changed['edit_revision'])
    assert undone['segments'][1]['end'] == -1


@pytest.mark.parametrize('field,value', [('end', 100), ('start', -2), ('speaker', 'invented'), ('text', ''), ('id', 'b')])
def test_invalid_restore_is_rejected_atomically(history, field, value):
    root, folder, initial = history
    invalid = copy.deepcopy(initial)
    invalid['segments'][0][field] = value
    with pytest.raises(ValueError):
        restore(root, invalid, initial['edit_revision'])
    assert not (folder / 'transcript-edits.json').exists()
