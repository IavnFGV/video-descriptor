"""Remove one completed result without touching its source or sibling versions."""

import shutil
from pathlib import Path

from .jobs import read_json, write_json
from .live import active_video


def checked_version(root, name):
    output = (Path(root) / 'output').resolve()
    if (not isinstance(name, str) or not name or name.startswith('.')
            or Path(name).name != name or name == 'jobs'):
        raise ValueError('Неизвестная версия')
    folder = output / name
    if folder.is_symlink() or folder.resolve().parent != output:
        raise ValueError('Неизвестная версия')
    manifest = read_json(folder / 'manifest.json', {})
    if not folder.is_dir() or not manifest.get('video'):
        raise ValueError('Версия не найдена')
    source = Path(manifest['video'])
    if not source.is_absolute():
        source = Path(root) / source
    if source.resolve().is_relative_to(folder.resolve()):
        raise ValueError('Исходный файл находится внутри версии; удаление недоступно')
    related = []
    for path in (output / 'jobs').glob('*/job.json'):
        job = read_json(path, {})
        if (job.get('status') in {'queued', 'running'}
                and (job.get('folder') == name or job.get('source_folder') == name
                     or job.get('video') == manifest['video'])):
            raise ValueError('Дождитесь завершения обработки этой записи')
        if job.get('folder') == name:
            related.append((path, job))
    if active_video(manifest['video']):
        raise ValueError('Дождитесь завершения обработки этой записи')
    return folder, related


def delete_version(root, name):
    folder, related = checked_version(root, name)
    shutil.rmtree(folder)
    for path, job in related:
        job['status'] = 'deleted'
        write_json(path, job)
    return {'deleted': name}


NOTE_FILES = {
    'report.html', 'notes.json', 'notes-live.json', 'notes.md', 'notes.user.md',
    'editor-default.md', 'chapters.json', 'construction-result.md',
    'construction-plan.json', 'analysis-errors.json',
}


def delete_notes(root, name, report=''):
    folder, _ = checked_version(root, name)
    if not isinstance(report, str) or (report and (report.startswith('.') or Path(report).name != report)):
        raise ValueError('Неизвестный конспект')
    target = folder / report if report else folder
    if target.is_symlink() or target.resolve().parent != (folder if report else folder.parent):
        raise ValueError('Неизвестный конспект')
    if not target.is_dir():
        raise ValueError('Конспект не найден')
    paths = [target / file for file in NOTE_FILES]
    for pattern in ('notes-*.json', 'chunk-plan-*.json', 'construction-part-*.md'):
        paths.extend(target.glob(pattern))
    for path in paths:
        if path.is_file() or path.is_symlink():
            path.unlink()
    write_json(target / 'notes-deleted.json', {'deleted': True})
    return {'deleted_notes': name, 'report': report}
