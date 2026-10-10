import pytest

from video_descriptor.jobs import read_json, write_json
from video_descriptor.versions import delete_notes, delete_version


def make_version(root, name='example', **manifest):
    folder = root / 'output' / name
    folder.mkdir(parents=True)
    write_json(folder / 'manifest.json', {'video': str(root / 'data' / 'video.mp4'), **manifest})
    write_json(folder / 'speech.json', {'status': 'done'})
    return folder


def test_delete_only_selected_version_and_hide_finished_job(tmp_path):
    source = tmp_path / 'data' / 'video.mp4'
    source.parent.mkdir()
    source.write_bytes(b'original video')
    old = make_version(tmp_path)
    new = make_version(tmp_path, 'new', version_of='example')
    (new / 'notes.user.md').write_text('Keep these notes')
    job = tmp_path / 'output' / 'jobs' / '123' / 'job.json'
    job.parent.mkdir(parents=True)
    write_json(job, {'folder': 'example', 'status': 'done'})
    delete_version(tmp_path, 'example')
    assert not old.exists()
    assert (new / 'notes.user.md').read_text() == 'Keep these notes'
    assert source.read_bytes() == b'original video'
    assert read_json(job)['status'] == 'deleted'


@pytest.mark.parametrize('name', ['', '.', '..', '../data', 'jobs', None])
def test_reject_invalid_path(tmp_path, name):
    with pytest.raises(ValueError):
        delete_version(tmp_path, name)


@pytest.mark.parametrize('status', ['queued', 'running'])
def test_block_deletion_when_dependent_job_is_active(tmp_path, status):
    folder = make_version(tmp_path)
    (tmp_path / 'output' / 'jobs' / '123').mkdir(parents=True)
    write_json(tmp_path / 'output' / 'jobs' / '123' / 'job.json',
               {'folder': 'new', 'source_folder': 'example', 'status': status})
    with pytest.raises(ValueError, match='завершения'):
        delete_version(tmp_path, 'example')
    assert folder.exists()


def test_reject_symlink_and_embedded_source(tmp_path):
    folder = make_version(tmp_path)
    (folder.parent / 'alias').symlink_to(folder, target_is_directory=True)
    with pytest.raises(ValueError):
        delete_version(tmp_path, 'alias')
    write_json(folder / 'manifest.json', {'video': str(folder / 'video.mp4')})
    with pytest.raises(ValueError, match='Исходный файл'):
        delete_version(tmp_path, 'example')
    assert folder.exists()


def test_delete_notes_preserves_recognition_and_other_report_variants(tmp_path):
    folder = make_version(tmp_path)
    keep = ['manifest.json', 'speech.json', 'transcript.json', 'transcript-edits.json',
            'translations.json', 'frames.json', 'frame.jpg', 'original.vtt',
            'ru.vtt', 'construction-settings.json']
    for name in keep[2:]:
        (folder / name).write_text('preserved')
    before = {name: (folder / name).read_bytes() for name in keep}
    remove = ['report.html', 'notes.json', 'notes.md', 'notes.user.md',
              'editor-default.md', 'chapters.json', 'notes-live.json',
              'construction-result.md', 'construction-part-abc.md',
              'notes-abc-0001.json', 'chunk-plan-abc.json']
    for name in remove:
        (folder / name).write_text('discard')
    other = folder / 'auto'
    other.mkdir()
    (other / 'report.html').write_text('other report')
    delete_notes(tmp_path, 'example')
    assert all(not (folder / name).exists() for name in remove)
    assert {name: (folder / name).read_bytes() for name in keep} == before
    assert (other / 'report.html').read_text() == 'other report'


def test_delete_nested_notes_preserves_main_report(tmp_path):
    folder = make_version(tmp_path)
    (folder / 'report.html').write_text('main report')
    nested = folder / 'off'
    nested.mkdir()
    (nested / 'report.html').write_text('variant')
    (nested / 'notes.user.md').write_text('manual edits')
    (nested / 'original.vtt').write_text('subtitles')
    delete_notes(tmp_path, 'example', 'off')
    assert (folder / 'report.html').read_text() == 'main report'
    assert not (nested / 'report.html').exists()
    assert not (nested / 'notes.user.md').exists()
    assert (nested / 'original.vtt').read_text() == 'subtitles'
    with pytest.raises(ValueError):
        delete_notes(tmp_path, 'example', '../example')


def test_partial_delete_blocked_during_processing(tmp_path):
    folder = make_version(tmp_path)
    (folder / 'report.html').write_text('keep')
    job = tmp_path / 'output' / 'jobs' / '123' / 'job.json'
    job.parent.mkdir(parents=True)
    write_json(job, {'folder': 'example', 'status': 'running'})
    with pytest.raises(ValueError, match='завершения'):
        delete_notes(tmp_path, 'example')
    assert (folder / 'report.html').read_text() == 'keep'
