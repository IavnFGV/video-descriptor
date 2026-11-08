"""Read the variants of one recording without changing its artifacts."""
from pathlib import Path
from urllib.parse import quote

from .jobs import read_json, video_url


def variants(root, *, folder='', job=''):
    root = Path(root).resolve()
    output = (root / 'output').resolve()
    if folder and (Path(folder).name != folder or folder in {'.', '..'}):
        raise ValueError('Неизвестная папка записи')
    if job and (len(job) != 32 or any(c not in '0123456789abcdef' for c in job)):
        raise ValueError('Неизвестное задание')
    selected_job = read_json(output / 'jobs' / job / 'job.json', {}) if job else {}
    if job and (not selected_job or selected_job.get('status') == 'deleted'):
        raise ValueError('Запись не найдена')
    folder = folder or selected_job.get('folder') or ''
    selected = (output / folder).resolve()
    selected.relative_to(output)
    manifest = read_json(selected / 'manifest.json', {}) if folder else {}
    video = manifest.get('video') or selected_job.get('video')
    if not video:
        raise ValueError('Запись не найдена')
    source = (root / video).resolve()
    source.relative_to((root / 'data').resolve())
    all_jobs = [value for path in (output / 'jobs').glob('*/job.json')
                if (value := read_json(path, {})).get('status') != 'deleted']
    jobs = {value['folder']: value for value in all_jobs if value.get('folder')}
    active = next((item for item in all_jobs if item.get('video') and
                   (root / item['video']).resolve() == source and item.get('status') in {'queued', 'running'}), None)
    speech, reports = [], []
    for path in output.glob('*/manifest.json'):
        directory = path.parent.resolve()
        try:
            directory.relative_to(output)
        except ValueError:
            continue
        data = read_json(path, {})
        if not data.get('video') or (root / data['video']).resolve() != source:
            continue
        current_job = jobs.get(directory.name, {})
        result = read_json(directory / 'speech.json', {})
        ready = result.get('status') == 'done' or (directory / 'transcript.json').is_file()
        created = current_job.get('created') or result.get('created') or path.stat().st_mtime
        speech.append({'folder': directory.name, 'job': current_job.get('id'),
                       'status': current_job.get('status', result.get('status', 'done')),
                       'cancelled': current_job.get('cancelled', False),
                       'ready': ready, 'created': created, 'engine': result.get('engine', ''),
                       'task': current_job.get('task', ''),
                       'internal_snapshot': current_job.get('mode') == 'notes' or current_job.get('task') == 'notes' or
                       (directory / 'construction-job.json').is_file(),
                       'result_kind': current_job.get('construction', {}).get('result_kind', 'notes'),
                       'source_folder': data.get('version_of')})
        for report in [directory, *sorted(p for p in directory.iterdir() if p.is_dir())]:
            if not (report / 'report.html').is_file() or (report == directory and not (report / 'notes.json').is_file()):
                continue
            try:
                relative = report.resolve().relative_to(output).as_posix()
                report.resolve().relative_to(directory)
            except ValueError:
                continue
            settings = read_json(report / 'construction-settings.json', {}) or current_job.get('construction', {})
            reports.append({'folder': directory.name, 'name': '' if report == directory else report.name,
                            'url': '/output/' + quote(relative, safe='/') + '/report.html',
                            'model': settings.get('model', ''), 'created': created,
                            'result_kind': settings.get('result_kind', 'notes'),
                            'speech_folder': directory.name})
    return {'folder': folder, 'filename': source.name, 'video_url': video_url(root, str(source)),
            'active_job': {**{key: active.get(key) for key in ('id', 'folder', 'status', 'task')},
                           'result_kind': active.get('construction', {}).get('result_kind', 'notes')} if active else None,
            'speech': sorted(speech, key=lambda x: x['created'], reverse=True),
            'reports': sorted(reports, key=lambda x: x['created'], reverse=True)}
