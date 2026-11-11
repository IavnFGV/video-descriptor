"""Manual fill of intervals whose model timestamps were unusable.

The gap stays outside the transcript until the user writes the text; the manual
answer becomes an ordinary reply that later stages treat as recognized text.
"""
import json

import pytest

from video_descriptor.jobs import write_json
from video_descriptor.models import Source
from video_descriptor.report import render
from video_descriptor.speech import edit_utterance, editable_result, subtitle_result
from video_descriptor.speech_recovery import pending_unresolved
from video_descriptor.subtitles import plain_transcript, webvtt

GAP = {'id': 'u-0000400000-0000480000', 'start': 25.0, 'end': 30.0, 'status': 'unresolved',
       'reason': 'invalid_timestamps'}


@pytest.fixture
def folder(tmp_path):
    directory = tmp_path / 'output' / 'speech'
    directory.mkdir(parents=True)
    rows = [{'id': 's1', 'start': 0, 'end': 25, 'text': 'Before the gap', 'speaker': 'one'},
            {'id': 's2', 'start': 30, 'end': 40, 'text': 'After the gap', 'speaker': 'unknown'}]
    write_json(directory / 'speech.json', {'status': 'done', 'duration': 40, 'segments': rows,
                                           'unresolved': [GAP]})
    write_json(directory / 'transcript.json', rows)
    return tmp_path, directory


def current(directory):
    return editable_result(directory, subtitle_result(directory))


def test_pending_interval_is_reported_with_its_exact_range(folder):
    _, directory = folder
    result = current(directory)
    assert [row['id'] for row in result['unresolved']] == [GAP['id']]
    note = result['unresolved'][0]['note']
    assert '00:00:25' in note and '00:00:30' in note
    assert 'таймкод' in note.lower()


def test_interval_is_not_part_of_the_transcript_until_it_is_written(folder):
    _, directory = folder
    result = current(directory)
    assert [row['id'] for row in result['segments']] == ['s1', 's2']
    assert GAP['id'] not in plain_transcript(result)
    assert GAP['id'] not in webvtt(result)


def test_manual_text_turns_the_interval_into_an_ordinary_reply(folder):
    root, directory = folder
    result = current(directory)
    saved = edit_utterance(root, {'folder': 'speech', 'revision': result['edit_revision'],
                                  'action': 'resolve', 'unresolved_id': GAP['id'],
                                  'text': 'The words the model could not time', 'speaker': 'one'})
    assert saved['unresolved'] == []
    filled = [row for row in saved['segments'] if row['id'] == GAP['id']]
    assert len(filled) == 1
    assert filled[0]['text'] == 'The words the model could not time'
    assert filled[0]['start'] == 25.0 and filled[0]['end'] == 30.0
    assert [row['id'] for row in saved['segments']] == ['s1', GAP['id'], 's2']
    assert 'The words the model could not time' in plain_transcript(saved)


def test_manual_answer_survives_a_reload(folder):
    root, directory = folder
    result = current(directory)
    edit_utterance(root, {'folder': 'speech', 'revision': result['edit_revision'],
                           'action': 'resolve', 'unresolved_id': GAP['id'],
                           'text': 'Written by hand', 'speaker': 'unknown'})
    reloaded = current(directory)
    assert reloaded['unresolved'] == []
    assert any(row['text'] == 'Written by hand' for row in reloaded['segments'])


def test_filling_the_same_interval_twice_is_rejected(folder):
    root, directory = folder
    result = current(directory)
    saved = edit_utterance(root, {'folder': 'speech', 'revision': result['edit_revision'],
                                  'action': 'resolve', 'unresolved_id': GAP['id'],
                                  'text': 'First answer', 'speaker': 'unknown'})
    with pytest.raises(ValueError, match='не найден или уже исправлен'):
        edit_utterance(root, {'folder': 'speech', 'revision': saved['edit_revision'],
                              'action': 'resolve', 'unresolved_id': GAP['id'],
                              'text': 'Second answer', 'speaker': 'unknown'})


def test_stale_revision_never_overwrites_a_filled_interval(folder):
    root, directory = folder
    stale = current(directory)
    edit_utterance(root, {'folder': 'speech', 'revision': stale['edit_revision'],
                           'action': 'resolve', 'unresolved_id': GAP['id'],
                           'text': 'Written by hand', 'speaker': 'unknown'})
    with pytest.raises(ValueError, match='изменились'):
        edit_utterance(root, {'folder': 'speech', 'revision': stale['edit_revision'],
                              'action': 'resolve', 'unresolved_id': GAP['id'],
                              'text': 'Late answer', 'speaker': 'unknown'})


@pytest.mark.parametrize('payload', [
    {'text': '', 'speaker': 'unknown'},
    {'text': 'Text', 'speaker': 'invented'},
    {'text': 'Text', 'speaker': 'unknown', 'start': -1},
    {'text': 'Text', 'speaker': 'unknown', 'end': 999},
    {'text': 'Text', 'speaker': 'unknown', 'start': 30, 'end': 25},
])
def test_invalid_manual_answer_is_rejected_atomically(folder, payload):
    root, directory = folder
    result = current(directory)
    request = {'folder': 'speech', 'revision': result['edit_revision'], 'action': 'resolve',
               'unresolved_id': GAP['id'], 'text': 'Text', 'speaker': 'unknown'}
    request.update(payload)
    with pytest.raises(ValueError):
        edit_utterance(root, request)
    assert not (directory / 'transcript-edits.json').exists()
    assert current(directory)['unresolved']


def test_undo_restores_the_interval_as_pending(folder):
    root, directory = folder
    result = current(directory)
    saved = edit_utterance(root, {'folder': 'speech', 'revision': result['edit_revision'],
                                  'action': 'resolve', 'unresolved_id': GAP['id'],
                                  'text': 'Written by hand', 'speaker': 'unknown'})
    undone = edit_utterance(root, {'folder': 'speech', 'revision': saved['edit_revision'],
                                   'action': 'restore', 'segments': result['segments'],
                                   'translations': result['translations']})
    assert [row['id'] for row in undone['unresolved']] == [GAP['id']]
    assert [row['id'] for row in undone['segments']] == ['s1', 's2']


def test_redo_after_undo_puts_the_manual_answer_back(folder):
    root, directory = folder
    result = current(directory)
    saved = edit_utterance(root, {'folder': 'speech', 'revision': result['edit_revision'],
                                  'action': 'resolve', 'unresolved_id': GAP['id'],
                                  'text': 'Written by hand', 'speaker': 'one'})
    undone = edit_utterance(root, {'folder': 'speech', 'revision': saved['edit_revision'],
                                   'action': 'restore', 'segments': result['segments'],
                                   'translations': result['translations']})
    redone = edit_utterance(root, {'folder': 'speech', 'revision': undone['edit_revision'],
                                   'action': 'restore', 'segments': saved['segments'],
                                   'translations': saved['translations']})
    assert redone['unresolved'] == []
    assert [row['id'] for row in redone['segments']] == ['s1', GAP['id'], 's2']
    assert redone['segments'][1]['text'] == 'Written by hand'


def test_pending_intervals_are_derived_from_the_recognized_rows():
    """A gap stops being pending once a reply carries its id."""
    assert [row['id'] for row in pending_unresolved([GAP], [{'id': 's1'}, {'id': GAP['id']}])] == []
    assert [row['id'] for row in pending_unresolved([GAP], [{'id': 's1'}])] == [GAP['id']]
    assert pending_unresolved(None, []) == []


def test_report_shows_the_interval_between_the_recognized_replies(folder, tmp_path):
    _, directory = folder
    video = tmp_path / 'video.mp4'
    video.touch()
    write_json(directory / 'manifest.json', {'video': str(video)})
    result = current(directory)
    sources = [Source(id=row['id'], start=row['start'], end=row['end'], text=row['text'])
               for row in result['segments']]
    render(directory, video, sources, [], None, {})
    page = (directory / 'report.html').read_text(encoding='utf-8')
    assert 'data-edit-gap="' + GAP['id'] + '"' in page
    assert 'Без таймкодов' in page
    assert '00:00:25' in page and '00:00:30' in page
    assert page.index('Before the gap') < page.index('Без таймкодов') < page.index('After the gap')


def test_unfilled_interval_is_absent_from_the_exported_transcript(folder):
    _, directory = folder
    result = current(directory)
    exported = plain_transcript(result)
    assert 'Before the gap' in exported and 'After the gap' in exported
    assert 'Без таймкодов' not in exported
    assert 'invalid_timestamps' not in exported


def test_versions_keep_the_pending_intervals(tmp_path):
    """A transcript version carries the recognition result and the pending gaps."""
    from video_descriptor.postprocess import enqueue
    directory = tmp_path / 'output' / 'speech'
    directory.mkdir(parents=True)
    rows = [{'id': 's1', 'start': 0, 'end': 25, 'text': 'Before the gap', 'speaker': 'unknown'}]
    write_json(directory / 'speech.json', {'status': 'done', 'duration': 40, 'segments': rows,
                                           'unresolved': [GAP]})
    write_json(directory / 'transcript.json', rows)
    write_json(directory / 'manifest.json', {'video': str(tmp_path / 'video.mp4')})
    (tmp_path / 'video.mp4').touch()
    job = enqueue(tmp_path, 'speech', 'notes', 'model', 'http://localhost:11434')
    version = tmp_path / 'output' / job['folder']
    saved = json.loads((version / 'speech.json').read_text(encoding='utf-8'))
    assert [row['id'] for row in saved['unresolved']] == [GAP['id']]
    assert GAP['id'] not in [row['id'] for row in saved['segments']]


def test_version_keeps_the_manual_answer_as_a_recognized_reply(tmp_path):
    """A filled interval stays an ordinary reply in a later transcript version."""
    from video_descriptor.postprocess import enqueue
    directory = tmp_path / 'output' / 'speech'
    directory.mkdir(parents=True)
    rows = [{'id': 's1', 'start': 0, 'end': 25, 'text': 'Before the gap', 'speaker': 'unknown'}]
    write_json(directory / 'speech.json', {'status': 'done', 'duration': 40, 'segments': rows,
                                           'unresolved': [GAP]})
    write_json(directory / 'transcript.json', rows)
    write_json(directory / 'manifest.json', {'video': str(tmp_path / 'video.mp4')})
    (tmp_path / 'video.mp4').touch()
    result = current(directory)
    edit_utterance(tmp_path, {'folder': 'speech', 'revision': result['edit_revision'],
                              'action': 'resolve', 'unresolved_id': GAP['id'],
                              'text': 'Written by hand', 'speaker': 'unknown'})
    job = enqueue(tmp_path, 'speech', 'notes', 'model', 'http://localhost:11434')
    version = tmp_path / 'output' / job['folder']
    saved = json.loads((version / 'speech.json').read_text(encoding='utf-8'))
    assert saved['unresolved'] == []
    filled = [row for row in saved['segments'] if row['id'] == GAP['id']]
    assert len(filled) == 1 and filled[0]['text'] == 'Written by hand'
    assert filled[0]['start'] == 25.0 and filled[0]['end'] == 30.0
