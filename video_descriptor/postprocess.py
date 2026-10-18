"""Queue local notes/translation from an immutable snapshot of corrected speech."""
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .action_history import record
from .construction import checked_folder, validate
from .jobs import jobs_dir, read_json, write_json
from .platform_support import lock_file
from .speech import editable_result, subtitle_result


def enqueue(root, name, task, model, base_url):
    root = Path(root).resolve()
    if task not in {'translate', 'notes'}:
        raise ValueError('Выберите перевод или конспект с переводом')
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9._:/-]{1,150}', model):
        raise ValueError('Выберите установленную модель Ollama')
    parsed = urlsplit(base_url)
    if (parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}
            or parsed.username or parsed.password or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
        raise ValueError('Для этой операции разрешена только локальная Ollama')
    source = checked_folder(root, name)
    manifest = read_json(source / 'manifest.json')
    result = editable_result(source, subtitle_result(source))
    if result.get('status') != 'done' or not result.get('segments'):
        raise ValueError('Сначала завершите распознавание записи с речью')
    with (root / 'output/postprocess.lock').open('a+') as lock:
        lock_file(lock)
        if any(read_json(p, {}).get('video') == manifest['video'] and
               read_json(p, {}).get('status') in {'queued', 'running'}
               for p in jobs_dir(root).glob('*/job.json')):
            raise ValueError('Эта запись уже находится в обработке')
        identity = uuid.uuid4().hex
        version = root / 'output' / ('processed-' + identity)
        version.mkdir()
        segments = [{**row, 'id': row.get('id', f's{index:05d}')}
                    for index, row in enumerate(result['segments'], 1)]
        write_json(version / 'manifest.json', {**manifest, 'version_of': name, 'mode': 'audio'})
        write_json(version / 'speech.json', {**result, 'segments': segments, 'folder': version.name,
                                           'job_id': identity, 'translations': {}, 'has_translation': False})
        write_json(version / 'transcript.json', [{k: row[k] for k in ('id', 'start', 'end', 'text')}
                                                for row in segments])
        write_json(version / 'frames.json', [])
        video = manifest['video']
        job = {'id': identity, 'video': video, 'filename': Path(video).name,
               'title': ('Конспект и перевод' if task == 'notes' else 'Перевод') + ' · ' + Path(video).name,
               'mode': 'postprocess', 'task': task, 'folder': version.name, 'source_folder': name,
               'translation_model': model, 'translation_base_url': base_url.rstrip('/'),
               'status': 'queued', 'created': time.time(), 'stage': 'queued'}
        if task == 'notes':
            job['construction'] = validate({'input': 'speech', 'provider': 'ollama', 'model': model,
                                            'context_tokens': 8192, 'output_tokens': 2048})
        target = jobs_dir(root) / identity
        target.mkdir()
        write_json(target / 'job.json', job)
    record('job_added', job_id=identity, stage=task)
    return job


def run(root, folder, job, log):
    result = root / 'output' / job['folder']
    if job['task'] == 'notes':
        job['stage'] = 'notes'
        write_json(folder / 'job.json', job)
        settings = folder / 'construction.json'
        write_json(settings, job['construction'])
        code = subprocess.run([sys.executable, '-u', '-m', 'video_descriptor.construction', str(root),
                               str(result), str(settings)], cwd=root, stdout=log, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, check=False).returncode
        if code:
            raise RuntimeError('Конспект остановлен; исходная расшифровка сохранена. См. журнал.')
    job['stage'] = 'translation'
    write_json(folder / 'job.json', job)
    code = subprocess.run([sys.executable, '-u', '-m', 'video_descriptor.translate', str(result),
                           '--model', job['translation_model'], '--local-model', job['translation_model'],
                           '--base-url', job['translation_base_url']], cwd=root, stdout=log,
                          stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, check=False).returncode
    if code:
        raise RuntimeError('Перевод остановлен; готовые блоки сохранены. Нажмите «Продолжить».')
    job['stage'] = 'done'
