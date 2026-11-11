"""Queue local notes/translation from an immutable snapshot of corrected speech."""
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .action_history import record
from .construction import checked_folder, validate, validate_provider
from .jobs import jobs_dir, read_json, run_process, write_json
from .ollama_connection import job_environment
from .platform_support import lock_file
from .speech import editable_result, subtitle_result


def enqueue(root, name, task, model, base_url, *, notes_model=None, construction=None, translate_after=True, translation_provider=None):
    root = Path(root).resolve()
    if task not in {'translate', 'notes'}:
        raise ValueError('Выберите перевод или конспект с переводом')
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9._:/@-]{1,150}', model):
        raise ValueError('Выберите установленную локальную модель')
    lm_selected = translation_provider == 'lmstudio' or (construction or {}).get('provider') == 'lmstudio'
    if lm_selected:
        from .lmstudio import base_url as lm_base_url
        base_url = lm_base_url(base_url)
    if not lm_selected:
        from .ollama_connection import endpoint_url
        base_url = endpoint_url(base_url)
    if type(translate_after) is not bool:
        raise TypeError('Выберите, нужен ли перевод реплик')
    config = validate(construction) if task == 'notes' and construction is not None else None
    if config:
        validate_provider(root, config)
        if config['result_kind'] == 'article':
            translate_after = False
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
               'title': (('Конспект и перевод' if translate_after else 'Конспект') if task == 'notes' else 'Перевод') + ' · ' + Path(video).name,
               'mode': 'postprocess', 'task': task, 'folder': version.name, 'source_folder': name,
               'translation_model': model, 'translation_base_url': base_url.rstrip('/'),
               'status': 'queued', 'created': time.time(), 'stage': 'queued'}
        if translation_provider:
            job['translation_provider'] = translation_provider
        if config and config['result_kind'] == 'article':
            job['title'] = 'Статья · ' + Path(video).name
        if task == 'notes':
            job['construction'] = config or validate({'input': 'speech', 'provider': 'ollama', 'model': notes_model or model,
                                            'context_tokens': 8192, 'output_tokens': 2048})
            job['translate_after'] = translate_after
            job['translation_provider'] = job['construction']['provider']
            if config:
                job['translation_model'] = config['model']
        target = jobs_dir(root) / identity
        target.mkdir()
        write_json(target / 'job.json', job)
    record('job_added', job_id=identity, stage=task)
    return job


def run(root, folder, job, log):
    if job['task'] == 'diarize':
        from .diarization_postprocess import run as diarize
        diarize(root, folder, job, log)
        return
    result = root / 'output' / job['folder']
    environment = ({**os.environ, 'VIDEO_DESCRIPTOR_JOB_LMSTUDIO_URL': job['translation_base_url']}
                   if job.get('translation_provider') == 'lmstudio' else job_environment(job['translation_base_url']))
    if job['task'] == 'notes':
        job['stage'] = 'notes'
        write_json(folder / 'job.json', job)
        settings = folder / 'construction.json'
        write_json(settings, job['construction'])
        code = run_process(folder, [sys.executable, '-u', '-m', 'video_descriptor.construction', str(root),
                               str(result), str(settings)], cwd=root, stdout=log, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, check=False, env=environment).returncode
        if code:
            detail = read_json(result / 'construction-error.json', {}).get('error')
            label = 'статью' if job['construction'].get('result_kind') == 'article' else 'конспект'
            raise RuntimeError('Не удалось создать ' + label + '. ' +
                               (detail[:1000] + ' ' if isinstance(detail, str) else '') +
                               'Исходная расшифровка сохранена.' +
                               (' Ответ модели также сохранён.' if (result / 'construction-result.md').is_file() else ''))
    if job['task'] == 'notes' and not job.get('translate_after', True):
        job['stage'] = 'done'
        return
    job['stage'] = 'translation'
    write_json(folder / 'job.json', job)
    option = {'gemini': '--gemini-model', 'lmstudio': '--lmstudio-model'}.get(job.get('translation_provider'), '--local-model')
    extra = ['--lmstudio-url', job['translation_base_url']] if job.get('translation_provider') == 'lmstudio' else []
    code = run_process(folder, [sys.executable, '-u', '-m', 'video_descriptor.translate', str(result),
                           '--model', job['translation_model'], option, job['translation_model'],
                           '--base-url', job['translation_base_url'], *extra], cwd=root, stdout=log,
                          stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, check=False, env=environment).returncode
    if code:
        raise RuntimeError('Перевод остановлен; готовые блоки сохранены. Нажмите «Продолжить».')
    job['stage'] = 'done'
