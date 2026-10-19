"""Checkpoint each VAD fragment with its engine; Auto retries only unfinished speech."""
import hashlib
import io
import math
import wave

import requests

from .action_history import record
from .jobs import read_json, write_json
from .local_backends import BackendUnavailable, ensure_backend
from .speech_npu import InvalidNPUTimestamps, speech_regions, timed_items


def wav_bytes(raw):
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(raw)
    return output.getvalue()


def transcribe(audio, folder, on_chunk, log, plan, job_id, language='auto'):
    with audio.open('rb') as source:
        checksum = hashlib.file_digest(source, 'sha256').hexdigest()
    identity = {'version': 1, 'audio_sha256': checksum, 'language': language,
                'requested': plan['requested'], 'initial_engine': plan['engine'],
                'backends': [{'device': b['device'], 'url': b['url']} for b in plan['backends']]}
    state_file = folder / 'device-state.json'
    state = read_json(state_file) or {'identity': identity, 'active': plan['selected'],
                                    'engines': {plan['selected']: plan['engine']}, 'switches': []}
    if state['identity'] != identity:
        raise ValueError('Модель, язык или профиль изменились: создайте новую версию речи')
    write_json(state_file, state)
    order = [b['device'] for b in plan['backends']]
    active = order.index(state['active'])
    result = []
    session = requests.Session()
    session.trust_env = False
    try:
        with wave.open(str(audio), 'rb') as stream:
            if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
                raise ValueError('Нужен mono PCM16 WAV 16000 Гц')
            total = stream.getnframes()
            offset, limit = 0, 300 * 16000
            while offset < total:
                count = min(limit, total - offset)
                completed_counts = [int(p.parent.name.rsplit('-', 1)[1])
                                    for p in folder.glob(f'local-{offset:010d}-*/complete.json')]
                completed_counts = [n for n in completed_counts if 0 < n <= min(300 * 16000, total - offset)]
                if completed_counts:
                    count = max(completed_counts)
                stream.setpos(offset)
                raw = stream.readframes(count)
                part = folder / f'local-{offset:010d}-{count:08d}'
                part.mkdir(exist_ok=True)
                saved_length = len(result)
                try:
                    vad = read_json(part / 'vad.json')
                    if vad is None:
                        vad = {'regions': speech_regions(raw)}
                        write_json(part / 'vad.json', vad)
                    for index, (first, last) in enumerate(vad['regions']):
                        region = part / f'speech-{index:04d}'
                        region.mkdir(exist_ok=True)
                        seconds = (last - first) / 16000
                        cached = read_json(region / 'response.json')
                        if cached is None:
                            while True:
                                backend = plan['backends'][active]
                                device = backend['device']
                                log(f'Распознаём на {device}: {(offset + first) / 16000:.1f}–{(offset + last) / 16000:.1f} сек записи; '
                                    f'всего {total / 16000:.1f} сек')
                                try:
                                    engine = ensure_backend(backend, plan['runtime'])
                                    if engine['model_sha256'] != plan['engine']['model_sha256']:
                                        raise ValueError('Файлы модели изменились. Создайте новую версию записи, чтобы не смешивать результаты разных моделей.')
                                    pinned = state['engines'].get(device)
                                    if pinned is not None and pinned != engine:
                                        raise ValueError('Версия сервиса распознавания изменилась. Создайте новую версию записи; прежний результат сохранён.')
                                    state['engines'][device] = engine
                                    write_json(state_file, state)
                                    http = session.post(backend['url'] + '/transcribe', data=wav_bytes(raw[first*2:last*2]),
                                                        headers={'Content-Type': 'audio/wav', 'X-Whisper-Model': 'small',
                                                                 'X-Language': language}, timeout=(5, 600))
                                    if not http.ok:
                                        (region / 'error.txt').write_text(http.text, encoding='utf-8')
                                        if 'timestamp' in http.text.lower():
                                            raise InvalidNPUTimestamps(f'{device}: модель вернула неверное время реплик на участке '
                                                             f'{(offset + first) / 16000:.1f}–{(offset + last) / 16000:.1f} сек. '
                                                             'Фрагмент не сохранён; выдуманные таймкоды не используются.')
                                        if http.status_code < 500:
                                            raise ValueError(f'{device}: сервис отклонил аудиофрагмент (HTTP {http.status_code}). '
                                                             'Проверьте выбранный язык и настройки модели.')
                                        raise BackendUnavailable(f'Ошибка сервиса распознавания (HTTP {http.status_code})')
                                    cached = http.json()
                                    if not isinstance(cached, dict):
                                        write_json(region / 'invalid-response.json', {'response': cached})
                                        raise TypeError('Некорректный формат ответа Whisper')
                                    if cached.get('engine') != engine:
                                        raise ValueError('Ответ пришёл от другой модели или устройства. Фрагмент не сохранён; проверьте настройки распознавания.')
                                    break
                                except (BackendUnavailable, requests.ConnectionError, requests.Timeout) as exc:
                                    record('device_attempt_failed', job_id=job_id, stage='speech',
                                           requested=plan['requested'], device=device, reason=type(exc).__name__)
                                    if plan['requested'] != 'AUTO' or active + 1 >= len(order):
                                        raise BackendUnavailable(f'{device}: сервис распознавания недоступен или не ответил вовремя. '
                                                                 'Уже сохранённый текст не потерян. Подготовьте распознавание '
                                                                 'в настройках AI и повторите запуск.') from exc
                                    active += 1
                                    state['active'] = order[active]
                                    state['switches'].append({'previous_device': device, 'device': order[active],
                                                              'reason': type(exc).__name__, 'sample': offset + first})
                                    write_json(state_file, state)
                                    record('device_fallback', job_id=job_id, requested=plan['requested'],
                                           previous_device=device, device=order[active], reason=type(exc).__name__)
                                    log(f'Авто: {device} недоступен → {order[active]}; повтор незавершённого фрагмента')
                        try:
                            reported = float(cached.get('audio_seconds', -1))
                            engine = cached['engine']
                            if (not math.isfinite(reported) or abs(reported - seconds) > .01
                                    or engine['device'] not in order or engine != state['engines'].get(engine['device'])):
                                raise ValueError('Ответ сервиса не соответствует отправленному аудио или выбранной модели. Фрагмент не сохранён; проверьте настройки модели.')
                            items, _ = timed_items(cached, (offset + first) / 16000, seconds)
                        except (ValueError, KeyError, TypeError):
                            write_json(region / 'invalid-response.json', cached)
                            raise
                        write_json(region / 'response.json', cached)
                        result.extend(items)
                        on_chunk(result, (offset + last) / 16000)
                except InvalidNPUTimestamps as exc:
                    if count <= 30 * 16000:
                        raise ValueError(str(exc) + ' Автоматическое восстановление не помогло. '
                                         'Сохранённый текст доступен; выберите другое устройство для новой версии записи.') from exc
                    limit = max(30 * 16000, count // 2)
                    log(f'Модель не определила время реплик. Повторяем незавершённый участок '
                        f'с {offset / 16000:.1f} сек блоком {limit / 16000:.1f} сек; устройство не меняем.')
                    # Keep response files, but do not mix text from different block boundaries.
                    result = result[:saved_length]
                    on_chunk(result, offset / 16000)
                    continue
                write_json(part / 'complete.json', {'frames': count})
                on_chunk(result, (offset + count) / 16000)
                offset += count
                limit = 300 * 16000
        return result, 'segment'
    finally:
        session.close()
