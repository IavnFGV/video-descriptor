"""Speech recognition with independent outputs and shared audio for the common pipeline."""
import hashlib
import json
import math
import os
import sys
import threading
import time
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from .jobs import jobs_dir, read_json, video_url, write_json
from .media import extract_audio, probe
from .translation_settings import load

ENGINES = {'gemini', 'gemini-diarization-xpu', 'whisper', 'whisper-diarization',
           'whisper-diarization-xpu', 'whisper-npu', 'whisper-npu-diarization-xpu'}
EXTENSIONS = {'.mp4', '.mkv', '.mov', '.webm', '.wav', '.mp3', '.m4a', '.flac', '.ogg'}
EDIT_LOCK = threading.RLock()


def editable_result(folder, result):
    result = dict(result)
    result['folder'] = folder.name
    transcript = read_json(folder / 'transcript.json', [])
    if transcript:
        result['segments'] = [{**row, 'id': transcript[index]['id']}
                              for index, row in enumerate(result['segments']) if index < len(transcript)]
    result['speaker_options'] = sorted({s['speaker'] for s in result['segments']} | {'unknown'})
    edits = read_json(folder / 'transcript-edits.json')
    if edits:
        result['segments'] = edits['segments']
    result['translations'] = {**read_json(folder / 'translations.json', {}),
                              **(edits or {}).get('translations', {})}
    if transcript or result['translations']:
        result['segments'] = [{**row, 'id': row.get('id', f's{index}')}
                              for index, row in enumerate(result['segments'], 1)]
    result['has_translation'] = bool(result['translations'])
    result['edit_revision'] = hashlib.sha256(
        json.dumps([result['segments'], result['translations']], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return result


def subtitle_result(folder):
    result = read_json(folder / 'speech.json')
    if result is None:
        transcript = read_json(folder / 'transcript.json')
        if transcript is None:
            raise ValueError('Субтитры ещё не подготовлены')
        result = {'status': 'done', 'segments': [{**row, 'speaker': 'unknown'} for row in transcript]}
    return result


def edit_utterance(root, value):
    name = value.get('folder')
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError('Неизвестная папка')
    folder = (root / 'output' / name).resolve()
    folder.relative_to((root / 'output').resolve())
    with EDIT_LOCK:
        original = subtitle_result(folder)
        if not original or original.get('status') != 'done':
            raise ValueError('Редактирование доступно после завершения распознавания')
        result = editable_result(folder, original)
        if value.get('revision') != result['edit_revision']:
            raise ValueError('Реплики изменились. Обновите страницу перед сохранением')
        index = value.get('index')
        if type(index) is not int or not 0 <= index < len(result['segments']):
            raise ValueError('Реплика не найдена')
        old = result['segments'][index]
        known = {s['speaker'] for s in original['segments']} | {'unknown'}

        def part(text, speaker, start, end):
            if not isinstance(text, str) or not text.strip() or len(text) > 100_000:
                raise ValueError('Укажите текст реплики (до 100 000 символов)')
            if not isinstance(speaker, str) or speaker not in known:
                raise ValueError('Выберите говорящего из списка')
            return {**old, 'text': text.strip(), 'speaker': speaker, 'start': start, 'end': end}

        if value.get('action') == 'edit':
            replacement = [part(value.get('text'), value.get('speaker'), old['start'], old['end'])]
        elif value.get('action') == 'split':
            at = value.get('at')
            if (type(at) not in (int, float) or not math.isfinite(at)
                    or not old['start'] < at < old['end']):
                raise ValueError('Время разделения должно находиться внутри исходной реплики')
            replacement = [part(value.get('text'), value.get('speaker'), old['start'], at),
                           part(value.get('right_text'), value.get('right_speaker'), at, old['end'])]
            if 'id' in old:
                replacement[1]['id'] = old['id'] + '-split-' + uuid.uuid4().hex[:12]
        else:
            raise ValueError('Неизвестная операция')
        segments = result['segments'][:index] + replacement + result['segments'][index + 1:]
        translations = read_json(folder / 'transcript-edits.json', {}).get('translations', {})
        for row, field in zip(replacement, ['translation', 'right_translation']):
            id = row.get('id')
            if id and (field in value or result['has_translation']):
                translated = value.get(field, result['translations'].get(id, '') if field == 'translation' else '')
                if not isinstance(translated, str) or len(translated) > 100_000:
                    raise ValueError('Перевод — до 100 000 символов')
                translations[id] = translated.strip()
        write_json(folder / 'transcript-edits.json', {'segments': segments, 'translations': translations,
                                                     'updated': time.time()})
        if (folder / 'manifest.json').is_file() and (folder / 'notes.json').is_file():
            from .translate import refresh_reports
            refresh_reports(folder)
        return editable_result(folder, original)


def source_path(root, value):
    path = (root / value).resolve()
    path.relative_to((root / 'data').resolve())
    if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
        raise ValueError('Выберите аудио или видео из data')
    return path


def validate_engine(root, engine):
    if engine not in ENGINES:
        raise ValueError('Неизвестный обработчик речи')
    if engine.startswith('whisper-npu'):
        from .speech_npu import health
        health()
    if engine.startswith('gemini'):
        settings = load(root)
        if not settings['api_key']:
            raise ValueError('Добавьте ключ Gemini в настройки')
        if settings['billing_mode'] == 'free' and not settings['free_ack']:
            raise ValueError('Подтвердите условия Free Tier в настройках')


def enqueue_existing(root, value, engine, title='', mode='audio', thinking=False, construction=None):
    if construction is not None:
        from .construction import validate, validate_provider
        construction = validate(construction)
        validate_provider(root, construction)
    video = source_path(root, value)
    if mode not in {'audio', 'lecture'}:
        raise ValueError('Неизвестный режим')
    if mode == 'audio' or construction is not None:
        validate_engine(root, engine)
    if mode == 'lecture' and video.suffix.lower() not in {'.mp4', '.mkv', '.mov', '.webm'}:
        raise ValueError('Для аудиофайла пропустите анализ изображения')
    if not isinstance(title, str) or len(title) > 200:
        raise ValueError('Название — до 200 символов')
    id = uuid.uuid4().hex
    folder = jobs_dir(root) / id
    folder.mkdir()
    job = {'id': id, 'video': str(video), 'filename': video.name, 'title': title, 'thinking': bool(thinking),
               'mode': mode, 'engine': engine, 'status': 'queued', 'created': time.time(), 'folder': None}
    if construction is not None:
        job['construction'] = construction
    write_json(folder / 'job.json', job)
    return job


def state(root, params):
    folder = None
    job = None
    if params.get('job'):
        id = params['job'][0]
        if len(id) != 32 or any(c not in '0123456789abcdef' for c in id):
            raise ValueError('Неизвестное задание')
        job = read_json(jobs_dir(root) / id / 'job.json')
        if not job or job.get('mode') not in {'audio', 'lecture'}:
            raise ValueError('Задание аудио не найдено')
        folder = job.get('folder')
    else:
        folder = params.get('folder', [''])[0]
    if not folder or Path(folder).name != folder:
        return {'job': job, 'result': None}
    resolved = (root / 'output' / folder).resolve()
    resolved.relative_to((root / 'output').resolve())
    result = subtitle_result(resolved)
    if result is None:
        raise ValueError('Результат не найден')
    if job is None and result.get('job_id'):
        job = read_json(jobs_dir(root) / result['job_id'] / 'job.json')
    recovery = read_json(root / 'output' / folder / 'npu-recovery.json', {})
    if (job and recovery.get('job_started') == job.get('started') and recovery.get('status') in {'running', 'done'}
            and job.get('status') in {'running', 'error'}):
        result = dict(result)
        result.update(processed=recovery['processed'], segments=recovery['segments'])
        gpu = result.get('parallel', {}).get('diarization', 'ожидание сохранения GPU')
        result.update(message=f"Текст: {recovery['message']} | Голоса: {gpu}", status='running')
        result['stage'] = 'diarization' if recovery['status'] == 'done' else 'parallel'
        job = {**job, 'status': 'running', 'error': None}
    if result.get('status') == 'done':
        result = editable_result(root / 'output' / folder, result)
    return {'job': job, 'result': result}


def inventory(root):
    sources = [str(p.relative_to(root)) for p in sorted((root / 'data').rglob('*'))
               if p.is_file() and p.suffix.lower() in EXTENSIONS]
    results = []
    for p in (root / 'output').glob('*/speech.json'):
        x = read_json(p, {})
        results.append({**{k: x.get(k) for k in ['folder', 'video', 'title', 'engine', 'status', 'created']},
                        'video_url': video_url(root, root / x['video']) if x.get('video') else None})
    return {'sources': sources, 'results': sorted(results, key=lambda x: x['created'] or 0, reverse=True)}


def group_words(words):
    rows = []
    for w in words:
        if (not rows or rows[-1]['speaker'] != w['speaker']
                or w['start'] - rows[-1]['end'] > 2 or w['end'] - rows[-1]['start'] > 20):
            rows.append(dict(w))
        else:
            rows[-1]['end'] = w['end']
            rows[-1]['text'] += ' ' + w['text'].strip()
    return rows


def google_chunk(audio, folder, key, *, diarization=True):
    """Keep exact provider response; auth headers never enter artifacts."""
    headers = {'x-goog-api-key': key}

    def check(r):
        if not r.ok:
            (folder / 'error.txt').write_text(r.text.replace(key, '[REDACTED]'))
            raise RuntimeError(f'Gemini HTTP {r.status_code}; подробности в error.txt')
        return r

    started = time.monotonic()
    uploaded = read_json(folder / 'upload.json')
    if not uploaded or time.time() - (folder / 'upload.json').stat().st_mtime > 3600:
        r = check(requests.post('https://generativelanguage.googleapis.com/upload/v1beta/files',
                               headers={**headers, 'X-Goog-Upload-Protocol': 'resumable',
                                        'X-Goog-Upload-Command': 'start',
                                        'X-Goog-Upload-Header-Content-Length': str(audio.stat().st_size),
                                        'X-Goog-Upload-Header-Content-Type': 'audio/wav'},
                               json={'file': {'display_name': 'audio transcription'}}, timeout=60))
        with audio.open('rb') as stream:
            uploaded = check(requests.post(r.headers['X-Goog-Upload-URL'], headers={
                **headers, 'X-Goog-Upload-Offset': '0', 'X-Goog-Upload-Command': 'upload, finalize'},
                data=stream, timeout=180)).json()['file']
        write_json(folder / 'upload.json', uploaded)
    payload = {'model': 'gemini-3.5-transcribe', 'input': [{
        'type': 'audio', 'uri': uploaded['uri'], 'mime_type': 'audio/wav'}],
        'generation_config': {'transcription_config': {'mode': {
            'type': 'verbatim', 'timestamp_granularities': ['word']}}}}
    if diarization:
        payload['generation_config']['transcription_config']['mode']['diarization_mode'] = 'speaker'
    write_json(folder.parent / 'recognition-settings.json', {
        'model': payload['model'], **payload['generation_config']})
    write_json(folder / 'request.json', payload)
    response = check(requests.post('https://generativelanguage.googleapis.com/v1beta/interactions',
                                  headers=headers, json=payload, timeout=600)).json()
    if response.get('status') != 'completed':
        write_json(folder / 'incomplete-response.json', response)
        raise RuntimeError('Gemini вернул незавершённое распознавание')
    write_json(folder / 'response.json', response)
    write_json(folder / 'measurement.json', {'seconds': time.monotonic() - started,
                                            'usage': response.get('usage')})
    return response


def diarize(root, audio, folder, device, update):
    diar = read_json(folder / 'diarization.json')
    if diar is not None:
        update('Диаризация восстановлена из кэша')
        return diar
    token = os.getenv('HF_TOKEN', '')
    env = root / '.env.huggingface'
    if not token and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith('HF_TOKEN='):
                token = line.partition('=')[2].strip().strip(chr(34) + chr(39))
    if not token:
        raise ValueError('Добавьте HF_TOKEN в .env.huggingface и откройте доступ к pyannote community-1')
    os.environ['PYANNOTE_METRICS_ENABLED'] = '0'
    import numpy as np
    import torch
    from pyannote.audio import Pipeline
    torch.set_num_threads(4)
    if device == 'xpu' and not torch.xpu.is_available():
        raise RuntimeError('Intel GPU недоступен: нужен PyTorch XPU и GPU-профиль контейнера')
    update(f'Диаризация · {device.upper()} · загрузка pyannote community-1')
    pipeline = Pipeline.from_pretrained('pyannote/speaker-diarization-community-1', token=token)
    pipeline.to(torch.device(device))
    if device == 'xpu':
        torch.xpu.synchronize()
    started = time.monotonic()
    with wave.open(str(audio)) as wav:
        rate = wav.getframerate()
        signal = torch.from_numpy(np.frombuffer(wav.readframes(wav.getnframes()),
                                               dtype='<i2').astype(np.float32) / 32768).unsqueeze(0)
    last = {}

    def hook(step_name, step_artifact, file=None, total=None, completed=None):
        percent = min(100, int(completed / total * 100)) if total and completed is not None else None
        if last.get(step_name, -1) != percent:
            last[step_name] = percent
            update(f'Диаризация · {device.upper()} · {step_name}' + (f' · {percent}%' if percent is not None else ''))
    prediction = pipeline({'waveform': signal, 'sample_rate': rate}, hook=hook)
    if device == 'xpu':
        torch.xpu.synchronize()
    diar = [{'start': s.start, 'end': s.end, 'speaker': sp}
            for s, sp in prediction.exclusive_speaker_diarization]
    write_json(folder / 'diarization.json', diar)
    write_json(folder / 'diarization-measurement.json', {
        'device': device, 'model': 'pyannote/speaker-diarization-community-1',
        'torch': torch.__version__, 'seconds': time.monotonic() - started})
    return diar


def assign_speakers(words, diar):
    for w in words:
        overlap, speaker = max(((max(0, min(w['end'], t['end']) - max(w['start'], t['start'])),
                                 t['speaker']) for t in diar), default=(0, 'unknown'))
        w['speaker'] = speaker if overlap else 'unknown'
    return words


def run(root, job_folder, job):
    video = source_path(root, job['video'])
    name = job.get('folder') or 'speech-' + job['id']
    folder = root / 'output' / name
    folder.mkdir(exist_ok=True)
    job['folder'] = name
    write_json(job_folder / 'job.json', job)
    stat = video.stat()
    identity = hashlib.sha256(f'{video}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()[:16]
    shared = root / 'output' / ('speech-audio-' + identity)
    shared.mkdir(exist_ok=True)
    duration = float(probe(video)['format']['duration'])
    write_json(folder / 'manifest.json', {'video': str(video), 'start': 0, 'duration': None,
                                         'processed_duration': duration, 'mode': 'audio', 'engine': job['engine']})
    result = read_json(folder / 'speech.json') or {
        'folder': name, 'video': str(video.relative_to(root)), 'title': job['title'] or video.name,
        'engine': job['engine'], 'duration': duration, 'created': time.time(), 'status': 'running',
        'message': 'Подготовка аудио', 'processed': 0, 'segments': [], 'speaker_names': {}}

    update_lock = threading.RLock()
    parallel_status = None
    pool = None
    diar_future = None

    def publish(message, processed=None):
        result.update(status='running', message=message, job_id=job['id'])
        if processed is not None:
            result['processed'] = processed
        write_json(folder / 'speech.json', result)
        print(time.strftime('%H:%M:%S'), message, flush=True)

    def update(message, processed=None):
        with update_lock:
            if parallel_status is not None:
                parallel_status['transcription'] = message
                result['parallel'] = dict(parallel_status)
                message = f"Текст: {message} | Голоса: {parallel_status['diarization']}"
            publish(message, processed)

    def gpu_update(message):
        with update_lock:
            parallel_status['diarization'] = message
            result['parallel'] = dict(parallel_status)
            publish(f"Текст: {parallel_status['transcription']} | Голоса: {message}")

    audio = shared / 'audio.wav'
    try:
        result['stage'] = 'preparation'
        update('Извлечение аудио · кадры и OCR отключены')
        if not audio.exists():
            extract_audio(video, audio, 0, duration)
        with wave.open(str(audio)) as wav:
            actual = wav.getnframes() / wav.getframerate()
        if abs(actual - duration) > 2:
            audio.unlink()
            raise RuntimeError('Аудио неполное; проверьте, завершено ли копирование файла')
        result['stage'] = 'transcription'
        if job['engine'] == 'whisper-npu-diarization-xpu':
            result['stage'] = 'parallel'
            parallel_status = {'transcription': 'запуск NPU', 'diarization': 'запуск GPU'}

            def gpu_work():
                try:
                    diar = diarize(root, audio, folder, 'xpu', gpu_update)
                    gpu_update('готово')
                    return diar
                except Exception as exc:
                    gpu_update(f'ошибка: {exc}')
                    raise

            pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='diarization-gpu')
            diar_future = pool.submit(gpu_work)
        if job['engine'].startswith('gemini'):
            key = load(root)['api_key']
            words = []
            for i, start in enumerate(range(0, int(duration) + 1, 900)):
                if start >= duration:
                    break
                part = folder / f'chunk-{i + 1:04}'
                part.mkdir(exist_ok=True)
                response = read_json(part / 'response.json')
                update(f'Gemini: фрагмент {i + 1}, {start:.0f}–{min(start + 900, duration):.0f} сек', start)
                if not response:
                    chunk = part / 'audio.wav'
                    if not chunk.exists():
                        extract_audio(audio, chunk, start, min(900, duration - start))
                    response = google_chunk(chunk, part, key) if job['engine'] == 'gemini' else google_chunk(chunk, part, key, diarization=False)
                for s in response.get('steps', []):
                    for c in s.get('content', []):
                        for w in c.get('annotations', []):
                            if w.get('type') == 'word_info':
                                words.append({'start': start + float(w['start_offset'].removesuffix('s')),
                                                  'end': start + float(w['end_offset'].removesuffix('s')),
                                                  'text': w['text'], 'speaker': f"Блок {i + 1} · {w.get('speaker', '?')}"})
                result['segments'] = group_words(words)
                update('Фрагмент сохранён', min(start + 900, duration))
            write_json(folder / 'words.json', words)
            result['speaker_notice'] = 'Метки голосов разных блоков независимы. Их можно вручную назвать одинаково после проверки.'
        elif job['engine'].startswith('whisper-npu'):
            from .speech_npu import transcribe

            def on_chunk(items, processed):
                result['segments'] = group_words(items)
                update('Whisper NPU: фрагмент сохранён', processed)

            words, timing = transcribe(audio, folder, on_chunk, update)
            result['timing'] = timing
            result['speaker_notice'] = ('Таймкоды отдельных слов' if timing == 'word' else
                                        'NPU возвращает таймкоды целых реплик; границы слов пока не определяются.')
        else:
            from faster_whisper import WhisperModel
            model_options = {'device': 'cpu', 'compute_type': 'int8', 'cpu_threads': 4}
            transcription_options = {'language': None, 'task': 'transcribe', 'beam_size': 5,
                                     'word_timestamps': True, 'vad_filter': True}
            result['recognition_parameters'] = {'model': 'small', **model_options, **transcription_options}
            update('Whisper small multilingual · CPU int8 · загрузка модели')
            model = WhisperModel('small', **model_options)
            words = []
            for i, start in enumerate(range(0, int(duration) + 1, 300)):
                if start >= duration:
                    break
                part = folder / f'chunk-{i + 1:04}'
                part.mkdir(exist_ok=True)
                saved = read_json(part / 'words.json')
                if saved is None:
                    chunk = part / 'audio.wav'
                    if not chunk.exists():
                        extract_audio(audio, chunk, start, min(300, duration - start))
                    segments, _ = model.transcribe(str(chunk), **transcription_options)
                    saved = []
                    for s in segments:
                        saved.extend({'start': start + w.start, 'end': start + w.end,
                                          'text': w.word.strip(), 'speaker': 'Без разметки'} for w in s.words or [])
                        result['segments'] = group_words(words + saved)
                        update(f'Whisper: {start + s.end:.0f}/{duration:.0f} сек', start + s.end)
                    write_json(part / 'words.json', saved)
                words.extend(saved)
            del model
        write_json(folder / 'words.json', words)
        if 'diarization' in job['engine']:
            device = 'xpu' if job['engine'].endswith('-xpu') else 'cpu'
            result['stage'] = 'diarization'
            result['speaker_notice'] = 'Единые метки голосов по всей записи · локальная диаризация ' + device.upper()
            if job['engine'].startswith('whisper-npu') and result.get('timing') != 'word':
                result['speaker_notice'] += (' · Говорящий назначается целой реплике по большей части её времени. '
                                            'При смене человека внутри реплики возможна неточность.')
            if diar_future is not None:
                update('NPU готов · ожидаем завершения GPU', duration)
                diar = diar_future.result()
                pool.shutdown(wait=True)
                pool = None
                parallel_status = None
                update('Объединение текста NPU и голосов GPU', duration)
            else:
                diar = diarize(root, audio, folder, device, update)
            words = assign_speakers(words, diar)
        result['segments'] = group_words(words)
        result.update(status='done', stage='done', processed=duration, message='Распознавание завершено')
        write_json(folder / 'speech.json', result)
    except Exception as exc:
        if pool is not None:
            update(f'NPU остановлен: {exc}; сохраняем результат начатой диаризации')
            pool.shutdown(wait=True)
        result.update(status='error', message=str(exc))
        write_json(folder / 'speech.json', result)
        raise


if __name__ == '__main__':
    job_file = Path(sys.argv[1]).resolve()
    run(Path.cwd(), job_file.parent, read_json(job_file))
