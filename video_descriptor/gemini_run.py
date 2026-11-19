"""Live overrides for one running Gemini construction, never global preferences."""

import re

from .action_history import record
from .editor import EditConflict
from .jobs import read_json, write_json

FILENAME = 'gemini-run-control.json'


def controls(job_folder, started):
    value = read_json(job_folder / FILENAME, {}) if job_folder else {}
    if started is None or value.get('started') != started:
        value = {}
    return {'model': value.get('model', ''), 'repeat': value.get('repeat') is True}


def active(root, folder, state):
    marker = state.get('gemini_run') or {}
    job_id = marker.get('id', '')
    started = marker.get('started')
    if not isinstance(job_id, str) or not re.fullmatch(r'[0-9a-f]{32}', job_id) or type(started) not in (int, float):
        return None
    target = root / 'output/jobs' / job_id
    job = read_json(target / 'job.json', {})
    if (job.get('id') != job_id or job.get('status') != 'running' or job.get('started') != marker.get('started')
            or job.get('folder') != folder.name or (job.get('construction') or {}).get('provider') != 'gemini'
            or (target / 'stop-request.json').exists()):
        return None
    return {'id': job_id, 'started': started, **controls(target, started)}


def save(root, value):
    folder = value.get('folder')
    model = value.get('model')
    repeat = value.get('repeat')
    if (not isinstance(folder, str) or not folder or folder in {'.', '..'}
            or re.search(r'[/\\:]', folder) or type(repeat) is not bool
            or not isinstance(model, str) or (model and not re.fullmatch(r'gemini-[A-Za-z0-9.-]{1,100}', model))):
        raise ValueError('Некорректные параметры текущего запуска Gemini')
    target = (root / 'output' / folder).resolve()
    target.relative_to((root / 'output').resolve())
    current = active(root, target, read_json(target / 'progress.json', {}))
    if not current or (current['id'], current['started']) != (value.get('id'), value.get('started')):
        raise EditConflict('Этот запуск Gemini уже завершён или сменился')
    updated = {**current, 'model': model, 'repeat': repeat}
    write_json(root / 'output/jobs' / current['id'] / FILENAME, updated)
    record('gemini_run_control', folder=target, job_id=current['id'], status='done',
           model=model or None, reason='retry_until_stopped' if repeat else 'bounded_retry')
    return updated
