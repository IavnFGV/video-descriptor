"""Multilingual Windows NPU transcription for the audio view, with chunk checkpoints."""
import io
import math
import os
import wave

import requests

from .jobs import read_json, write_json


def worker_url():
    # Independent from the English lecture worker on port 8765.
    return os.getenv('SPEECH_NPU_URL', 'http://host.docker.internal:8766').rstrip('/')


def health():
    try:
        response = requests.get(worker_url() + '/health', timeout=(3, 5))
        response.raise_for_status()
        engine = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ValueError('Whisper NPU недоступен: запустите многоязычный Windows-сервис на 8766') from exc
    if engine.get('word_timestamps', False) or (engine.get('protocol'), engine.get('device'), engine.get('model'),
            engine.get('multilingual'), engine.get('pipeline'), engine.get('num_beams')) != (
                1, 'NPU', 'small', True, 'static', 1):
        raise ValueError('Нужен Windows Whisper small multilingual · NPU · static · beam=1')
    return engine


def timed_items(response, offset, seconds):
    """Use genuine word timing when supplied; never fabricate word boundaries."""
    word_timing = bool(response.get('words'))
    items = response['words'] if word_timing else response.get('segments')
    if not isinstance(items, list):
        raise TypeError('Whisper NPU: в ответе нет списка реплик или слов')
    result = []
    for item in items:
        start = float(item.get('start', item.get('start_ts')))
        end = float(item.get('end', item.get('end_ts')))
        if end == -1:
            raise ValueError('Whisper NPU: end_ts=-1, конечная граница не предсказана; нужна проверка фрагмента')
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end <= seconds + .01):
            raise ValueError('Whisper NPU: неверные таймкоды в ответе')
        text = item['text'].strip()
        if text:
            result.append({'start': offset + start, 'end': offset + end,
                           'text': text, 'speaker': 'Без разметки'})
    return result, 'word' if word_timing else 'segment'


def speech_regions(raw):
    """Silero VAD on CPU; returned sample offsets retain the original audio clock."""
    import numpy as np
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    detected = get_speech_timestamps(
        np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768,
        VadOptions(min_speech_duration_ms=100, speech_pad_ms=400), sampling_rate=16000)
    groups = []
    for region in detected:
        start, end = region['start'], region['end']
        if groups and start - groups[-1][1] <= 2 * 16000:
            groups[-1] = (groups[-1][0], end)
        else:
            groups.append((start, end))
    return groups


class InvalidNPUTimestamps(RuntimeError):
    pass


def request_with_vad(raw, part, engine, offset, log):
    seconds = len(raw) / 32000
    vad_file = part / 'vad.json'
    vad = read_json(vad_file)
    if vad is None:
        log(f'VAD: проверка речи · {offset:g}–{offset + seconds:g} сек')
        vad = {'version': 1, 'min_speech_duration_ms': 100, 'speech_pad_ms': 400,
               'regions': speech_regions(raw)}
        write_json(vad_file, vad)
    regions = vad['regions']
    if not regions:
        log(f'VAD: без речи · {offset:g}–{offset + seconds:g} сек · NPU не вызываем')
        return {'engine': engine, 'audio_seconds': seconds, 'segments': [], 'seconds': 0,
                'skipped': 'no_speech', 'vad': vad}
    collected, timings, elapsed = [], set(), 0
    for i, (first, last) in enumerate(regions):
        folder = part / f'speech-{i + 1:04d}'
        folder.mkdir(exist_ok=True)
        duration = (last - first) / 16000
        response = read_json(folder / 'response.json')
        if response is None:
            body = io.BytesIO()
            with wave.open(body, 'wb') as wav:
                wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                wav.writeframes(raw[first * 2:last * 2])
            write_json(folder / 'request.json', {
                'url': worker_url() + '/transcribe', 'model': 'small', 'language': os.getenv('SPEECH_LANGUAGE', 'auto'),
                'start': offset + first / 16000, 'audio_seconds': duration,
                'wav_bytes': len(body.getvalue()), 'engine': engine})
            log(f'VAD → NPU: речь {offset + first / 16000:g}–{offset + last / 16000:g} сек · '
                f'отправлено={duration:g} сек')
            http = requests.post(worker_url() + '/transcribe', data=body.getvalue(),
                                 headers={'Content-Type': 'audio/wav', 'X-Whisper-Model': 'small',
                                          'X-Language': os.getenv('SPEECH_LANGUAGE', 'auto')}, timeout=(5, 600))
            if not http.ok:
                (folder / 'error.txt').write_text(http.text)
                if http.status_code == 500 and 'invalid timestamps' in http.text:
                    raise InvalidNPUTimestamps(f'Whisper NPU: неверные таймкоды; см. {folder}/error.txt')
                raise RuntimeError(f'Whisper NPU: HTTP {http.status_code}; см. {folder}/error.txt')
            response = http.json()
        reported = float(response.get('audio_seconds', -1))
        if response.get('engine') != engine or not math.isfinite(reported) or abs(reported - duration) > .01:
            raise ValueError('Whisper NPU: модель или длительность ответа не совпали с запросом')
        try:
            items, timing = timed_items(response, first / 16000, duration)
        except (ValueError, TypeError, KeyError):
            write_json(folder / 'invalid-response.json', response)
            raise
        write_json(folder / 'response.json', response)
        collected.extend(items)
        timings.add(timing)
        elapsed += response.get('seconds', 0)
    key = 'words' if timings == {'word'} else 'segments'
    return {'engine': engine, 'audio_seconds': seconds, key: collected, 'seconds': elapsed,
            'vad': vad, 'timing': next(iter(timings)) if len(timings) == 1 else 'mixed'}


def transcribe(audio, folder, on_chunk, log):
    engine = health()
    language = os.getenv('SPEECH_LANGUAGE', 'auto')
    if language not in {'auto', 'en', 'ru', 'uk'}:
        raise ValueError('Неизвестный язык NPU')
    legacy_language = 'auto' if (folder / 'npu-engine.json').exists() else language
    previous_language = read_json(folder / 'npu-language.json', {'language': legacy_language})
    if previous_language['language'] != language:
        raise ValueError('Язык изменился: создайте новую версию речи, чтобы сохранить кэш')
    write_json(folder / 'npu-language.json', {'language': language})
    previous = read_json(folder / 'npu-engine.json')
    if previous and previous != engine:
        raise ValueError('NPU-модель или режим изменились: создайте новый вариант, чтобы не смешивать кэш')
    write_json(folder / 'npu-engine.json', engine)
    write_json(folder / 'recognition-settings.json', {
        name: engine[name] for name in ('model', 'device', 'multilingual', 'pipeline', 'num_beams') if name in engine})
    collected, timings = [], set()
    with wave.open(str(audio), 'rb') as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
            raise ValueError('Whisper NPU: нужен mono PCM16 WAV 16000 Гц')
        total, offset, limit = stream.getnframes(), 0, 300 * 16000
        while offset < total:
            count = min(limit, total - offset)
            completed_counts = [int(p.parent.name.rsplit('-', 1)[1]) for p in
                                folder.glob(f'npu-{offset:010d}-*/response.json')]
            completed_counts = [n for n in completed_counts if 0 < n <= min(300 * 16000, total - offset)]
            if completed_counts:
                count = max(completed_counts)
            part = folder / f'npu-{offset:010d}-{count:08d}'
            part.mkdir(exist_ok=True)
            cached = read_json(part / 'response.json')
            seconds = count / 16000
            log(f'Whisper small NPU · {offset / 16000:.0f}–{(offset + count) / 16000:.0f} сек · '
                f'видео={seconds:g} сек · ' + ('из кэша' if cached is not None else 'отправка'))
            if cached is None:
                stream.setpos(offset)
                raw = stream.readframes(count)
                try:
                    cached = request_with_vad(raw, part, engine, offset / 16000, log)
                except InvalidNPUTimestamps:
                    if count <= 30 * 16000:
                        raise
                    limit = max(30 * 16000, count // 2)
                    log(f'NPU: повтор с того же места блоком {limit / 16000:g} сек')
                    continue
            reported_seconds = float(cached.get('audio_seconds', -1))
            if (cached.get('engine') != engine or not math.isfinite(reported_seconds)
                    or abs(reported_seconds - seconds) > .01):
                raise ValueError('Whisper NPU: модель или длительность ответа не совпали с запросом')
            items, timing = timed_items(cached, offset / 16000, seconds)
            write_json(part / 'response.json', cached)
            collected.extend(items)
            if items:
                timings.add(cached.get('timing', timing))
            offset += count
            on_chunk(collected, offset / 16000)
            log(f'NPU: сохранено {offset / 16000:.0f}/{total / 16000:.0f} сек · '
                f'{len(items)} элементов · обработка {cached.get("seconds", 0):.2f} сек · таймкоды={timing}')
            limit = 300 * 16000
    return collected, next(iter(timings)) if len(timings) == 1 else ('mixed' if timings else 'segment')
