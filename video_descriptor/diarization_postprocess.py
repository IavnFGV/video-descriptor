"""Add speaker labels to a snapshot of completed speech in an independent native job."""
import hashlib
import json
import math
import subprocess
import time
import uuid
from pathlib import Path

from .construction import checked_folder
from .jobs import jobs_dir, read_json, write_json
from .media import extract_audio
from .platform_support import lock_file, subprocess_options
from .speech import assign_speakers, editable_result, source_path, subtitle_result

WORKER = Path(__file__).resolve().parents[1] / 'windows-app/diarization_worker.py'


def publish(path, value):
    for attempt in range(20):
        try:
            write_json(path, value)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(.05)


def model_digest(folder):
    digest = hashlib.sha256()
    for path in sorted(Path(folder).rglob('*')):
        if path.is_file():
            digest.update(path.relative_to(folder).as_posix().encode())
            with path.open('rb') as stream:
                digest.update(hashlib.file_digest(stream, 'sha256').digest())
    return digest.hexdigest()


def status(settings):
    python = Path(settings.get('diarization_python') or '__missing__')
    model = Path(settings.get('diarization_model_directory') or '__missing__')
    configured = python.is_file() and (model / 'config.yaml').is_file()
    device = settings.get('diarization_device', 'cpu')
    return {'state': 'configured' if configured else 'setup_required', 'device': device,
            'message': (f'Настроено · {device.upper()} · запускается по запросу' +
                        (' · ' + settings['diarization_setup_warning'] if settings.get('diarization_setup_warning') else '')) if configured else
                       'Нужны отдельное Python-окружение и локальная модель pyannote community-1.'}


def enqueue(root, name, settings):
    root = Path(root).resolve()
    if status(settings)['state'] != 'configured':
        raise ValueError(status(settings)['message'])
    device = settings.get('diarization_device', 'cpu')
    if device not in {'cpu', 'xpu'}:
        raise ValueError('Для говорящих выберите CPU или Intel GPU/XPU; NPU не поддерживается.')
    source = checked_folder(root, name)
    result = editable_result(source, subtitle_result(source))
    if result.get('status') != 'done' or not result.get('segments'):
        raise ValueError('Сначала завершите распознавание записи с речью.')
    manifest = read_json(source / 'manifest.json', {})
    video = source_path(root, manifest.get('video', ''))
    with (root / 'output/postprocess.lock').open('a+') as lock:
        lock_file(lock)
        if any(read_json(p, {}).get('video') == str(video) and
               read_json(p, {}).get('status') in {'queued', 'running'} for p in jobs_dir(root).glob('*/job.json')):
            raise ValueError('Эта запись уже находится в обработке.')
        identity = uuid.uuid4().hex
        target = root / 'output' / ('diarized-' + identity)
        target.mkdir()
        segments = [{**row, 'id': row.get('id', f's{index:05d}')}
                    for index, row in enumerate(result['segments'], 1)]
        write_json(target / 'manifest.json', {**manifest, 'version_of': name, 'mode': 'audio'})
        write_json(target / 'speech.json', {**result, 'folder': target.name, 'job_id': identity,
                                           'segments': segments, 'status': 'queued',
                                           'message': 'Говорящие: ожидаем запуска', 'stage': 'diarization'})
        write_json(target / 'transcript.json', [{k: row[k] for k in ('id', 'start', 'end', 'text')}
                                               for row in segments])
        write_json(target / 'translations.json', result.get('translations', {}))
        job = {'id': identity, 'video': str(video), 'filename': video.name,
               'title': 'Говорящие · ' + (result.get('title') or video.name), 'mode': 'postprocess',
               'task': 'diarize', 'stage': 'diarization', 'source_folder': name, 'folder': target.name,
               'diarization_python': str(Path(settings['diarization_python']).resolve()),
               'diarization_model_directory': str(Path(settings['diarization_model_directory']).resolve()),
               'diarization_model_sha256': model_digest(Path(settings['diarization_model_directory'])),
               'diarization_device': device, 'status': 'queued', 'created': time.time()}
        folder = jobs_dir(root) / identity
        folder.mkdir()
        write_json(folder / 'job.json', job)
    return job


def validate_turns(turns, duration):
    if not isinstance(turns, list):
        raise TypeError('Сервис не вернул разметку говорящих. Исходный текст сохранён.')
    for row in turns:
        if (not isinstance(row, dict) or not isinstance(row.get('speaker'), str) or
                any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k]) for k in ('start', 'end')) or
                not 0 <= row['start'] <= row['end'] <= duration + .1):
            raise ValueError('Неверные границы говорящих. Исходный текст сохранён.')
    return turns


def run(root, folder, job, log):
    target = root / 'output' / job['folder']
    result = read_json(target / 'speech.json')
    result.update(status='running', message='Говорящие: подготавливаем аудио без повторного распознавания')
    publish(target / 'speech.json', result)
    video = source_path(root, job['video'])
    stat = video.stat()
    identity = hashlib.sha256(f'{video}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()[:16]
    shared = root / 'output' / ('speech-audio-' + identity)
    shared.mkdir(exist_ok=True)
    audio = shared / 'audio.wav'
    if not audio.exists():
        extract_audio(video, audio, 0, result['duration'])
    output, progress = target / 'diarization-result.json', target / 'diarization-progress.json'
    try:
        if model_digest(Path(job['diarization_model_directory'])) != job['diarization_model_sha256']:
            raise ValueError('Модель диаризации изменилась после запуска. Создайте новую версию с говорящими.')
        if not output.exists():
            errors = target / 'diarization-error.log'
            command = [job['diarization_python'], '-X', 'utf8', '-u', str(WORKER),
                       '--audio', str(audio), '--model', job['diarization_model_directory'],
                       '--device', job['diarization_device'], '--output', str(output), '--progress', str(progress)]
            with errors.open('w', encoding='utf-8') as stderr:
                process = subprocess.Popen(command, stdout=log, stderr=stderr, stdin=subprocess.DEVNULL,
                                           **subprocess_options())
                while process.poll() is None:
                    result.update(message=read_json(progress, {}).get('message', result['message']))
                    publish(target / 'speech.json', result)
                    time.sleep(.5)
            if process.returncode:
                detail = ''
                for line in reversed(errors.read_text(encoding='utf-8', errors='replace').splitlines()):
                    try:
                        detail = json.loads(line).get('error', '')
                        if detail:
                            break
                    except (ValueError, AttributeError):
                        continue
                raise RuntimeError('Не удалось разделить голоса. ' +
                                   (detail[:500] or 'Проверьте Python-окружение и локальную модель диаризации.') +
                                   ' Исходная расшифровка сохранена.')
        report = read_json(output)
        if not isinstance(report, dict):
            raise TypeError('Кэш голосов повреждён. Создайте новую версию с говорящими; исходный текст сохранён.')
        with audio.open('rb') as stream:
            audio_sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
        if report.get('audio_sha256') != audio_sha256:
            raise ValueError('Разметка голосов относится к другому аудио. Исходный текст сохранён.')
        if report.get('device') != job['diarization_device'] or abs(report.get('duration', -1) - result['duration']) > .1:
            raise ValueError('Ответ диаризации не совпал с записью или выбранным устройством.')
        turns = validate_turns(report.get('turns'), result['duration'])
        result['segments'] = assign_speakers([dict(row) for row in result['segments']], turns)
        speakers = sorted({row['speaker'] for row in result['segments']} - {'unknown'})
        result.update(status='done', message='Говорящие определены' if speakers else
                      'Голоса не определены; реплики оставлены без говорящего. Доступна ручная разметка.', stage='done',
                      speaker_names={speaker: f'Говорящий {index}' for index, speaker in enumerate(speakers, 1)},
                      diarization_device=job['diarization_device'],
                      speaker_notice='Говорящий назначен по наибольшему пересечению с репликой. '
                                     'Смена голоса внутри одной реплики может потребовать ручной правки.')
        write_json(target / 'diarization.json', turns)
        publish(target / 'speech.json', result)
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        result.update(status='error', message=str(exc))
        publish(target / 'speech.json', result)
        raise RuntimeError(str(exc)) from exc
    job['stage'] = 'done'
