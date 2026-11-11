"""Gate blocks with VAD and retain model context; checkpoint per engine and retry safely."""
import hashlib
import io
import json
import math
import wave

import requests

from .action_history import record
from .jobs import read_json, write_json
from .local_backends import BackendUnavailable, ensure_backend
from .speech_npu import speech_regions, timed_items
from .speech_recovery import (
    MAX_RECOVERY_DEPTH,
    InvalidTimestamps,
    InvalidWorkerTimestamps,
    InvocationBudget,
    split_interval,
    unresolved_entry,
)

BLOCK_FRAMES = 300 * 16000


def wav_bytes(raw):
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(raw)
    return output.getvalue()


def timestamp_rejection(http):
    """Return the worker's timestamp diagnostics, or None when the failure is not the model's."""
    try:
        payload = json.loads(http.text or '')
    except ValueError:
        payload = None
    if isinstance(payload, dict) and payload.get('code') == 'invalid_timestamps':
        return {'invalid': payload.get('invalid') or {}}
    if 'invalid timestamp' in (http.text or '').lower():
        return {'invalid': {}}
    return None


class _Transcriber:
    """Recognizes one recording; unusable model timestamps split the failing interval."""

    def __init__(self, session, plan, state, state_file, job_id, language, log, on_chunk,
                 on_unresolved):
        self.session = session
        self.plan = plan
        self.state = state
        self.state_file = state_file
        self.job_id = job_id
        self.language = language
        self.log = log
        self.on_chunk = on_chunk
        self.on_unresolved = on_unresolved
        self.order = [backend['device'] for backend in plan['backends']]
        self.active = self.order.index(state['active'])
        self.result = []
        self.budget = InvocationBudget()

    def publish(self, items, processed):
        """Publish recognized rows together with the reached position."""
        self.result.extend(items)
        self.on_chunk(self.result, processed)

    def request(self, directory, payload, first, last, absolute_first, absolute_last):
        """Send one interval to the active device; only model failures are recoverable."""
        while True:
            backend = self.plan['backends'][self.active]
            device = backend['device']
            self.log(f'Распознаём на {device}: {absolute_first / 16000:.1f}–{absolute_last / 16000:.1f} сек записи; '
                     f'всего {self.total / 16000:.1f} сек')
            try:
                engine = ensure_backend(backend, self.plan['runtime'])
                if engine['model_sha256'] != self.plan['engine']['model_sha256']:
                    raise ValueError('Файлы модели изменились. Создайте новую версию записи, чтобы не смешивать результаты разных моделей.')
                pinned = self.state['engines'].get(device)
                if pinned is not None and pinned != engine:
                    raise ValueError('Версия сервиса распознавания изменилась. Создайте новую версию записи; прежний результат сохранён.')
                self.state['engines'][device] = engine
                write_json(self.state_file, self.state)
                if not self.budget.take():
                    raise InvalidWorkerTimestamps(
                        f'{device}: исчерпан лимит обращений к модели при восстановлении таймкодов '
                        f'на участке {absolute_first / 16000:.1f}–{absolute_last / 16000:.1f} сек.',
                        {'limit': self.budget.limit})
                http = self.session.post(backend['url'] + '/transcribe', data=payload,
                                         headers={'Content-Type': 'audio/wav', 'X-Whisper-Model': 'small',
                                                  'X-Language': self.language}, timeout=(5, 600))
                if not http.ok:
                    (directory / 'error.txt').write_text(http.text, encoding='utf-8')
                    rejection = timestamp_rejection(http)
                    if rejection is not None:
                        raise InvalidWorkerTimestamps(
                            f'{device}: модель вернула неверное время реплик на участке '
                            f'{absolute_first / 16000:.1f}–{absolute_last / 16000:.1f} сек. '
                            'Фрагмент не сохранён; выдуманные таймкоды не используются.',
                            rejection)
                    if http.status_code < 500:
                        raise ValueError(f'{device}: сервис отклонил аудиофрагмент (HTTP {http.status_code}). '
                                         'Проверьте выбранный язык и настройки модели.')
                    raise BackendUnavailable(f'Ошибка сервиса распознавания (HTTP {http.status_code})')
                cached = http.json()
                if not isinstance(cached, dict):
                    write_json(directory / 'invalid-response.json', {'response': str(cached)})
                    raise TypeError('Некорректный формат ответа Whisper')
                if cached.get('engine') != engine:
                    raise ValueError('Ответ пришёл от другой модели или устройства. Фрагмент не сохранён; проверьте настройки распознавания.')
                return cached
            except (BackendUnavailable, requests.ConnectionError, requests.Timeout) as exc:
                record('device_attempt_failed', job_id=self.job_id, stage='speech',
                       requested=self.plan['requested'], device=device, reason=type(exc).__name__)
                if self.plan['requested'] != 'AUTO' or self.active + 1 >= len(self.order):
                    raise BackendUnavailable(f'{device}: сервис распознавания недоступен или не ответил вовремя. '
                                             'Уже сохранённый текст не потерян. Подготовьте распознавание '
                                             'в настройках AI и повторите запуск.') from exc
                self.active += 1
                self.state['active'] = self.order[self.active]
                self.state['switches'].append({'previous_device': device, 'device': self.order[self.active],
                                              'reason': type(exc).__name__, 'sample': absolute_first})
                write_json(self.state_file, self.state)
                record('device_fallback', job_id=self.job_id, requested=self.plan['requested'],
                       previous_device=device, device=self.order[self.active], reason=type(exc).__name__)
                self.log(f'Авто: {device} недоступен → {self.order[self.active]}; повтор незавершённого фрагмента')

    def recognize(self, directory, raw, first, last, absolute, depth):
        """Recognize one interval; unusable model timestamps split it into halves."""
        cached = read_json(directory / 'response.json')
        failure = read_json(directory / 'invalid-timestamps.json')
        if cached is None and failure is None:
            try:
                cached = self.request(directory, wav_bytes(raw[first * 2:last * 2]), first, last,
                                      absolute, absolute + last - first)
            except InvalidTimestamps as exc:
                failure = {'code': 'invalid_timestamps', 'detail': exc.details}
                write_json(directory / 'invalid-timestamps.json', failure)
        if cached is None:
            return self.recover(directory, raw, first, last, absolute, depth, failure or {})
        seconds = (last - first) / 16000
        reported = float(cached.get('audio_seconds', -1))
        engine = cached.get('engine') or {}
        if (not math.isfinite(reported) or abs(reported - seconds) > .01
                or engine.get('device') not in self.order
                or engine != self.state['engines'].get(engine.get('device'))):
            raise ValueError('Ответ сервиса не соответствует отправленному аудио или выбранной модели. '
                             'Фрагмент не сохранён; проверьте настройки модели.')
        try:
            items, _ = timed_items(cached, absolute / 16000, seconds)
        except InvalidTimestamps as exc:
            write_json(directory / 'invalid-response.json', cached)
            write_json(directory / 'invalid-timestamps.json',
                       {'code': 'invalid_timestamps', 'detail': exc.details})
            return self.recover(directory, raw, first, last, absolute, depth,
                                {'code': 'invalid_timestamps', 'detail': exc.details})
        write_json(directory / 'response.json', cached)
        return items, []

    def recover(self, directory, raw, first, last, absolute, depth, failure):
        """Split a failing interval in half; a window that still fails stays unresolved."""
        end = absolute + last - first
        middle = split_interval(absolute, end)
        if middle is None or depth >= MAX_RECOVERY_DEPTH or self.budget.exhausted:
            reason = 'invalid_timestamps' if middle is None else 'recovery_limit'
            entry = unresolved_entry(absolute, end, reason, failure.get('detail'))
            if self.on_unresolved:
                self.on_unresolved(entry)
            record('speech_timestamps_unresolved', job_id=self.job_id, stage='speech',
                   device=self.plan['backends'][self.active]['device'], reason=reason, status='error')
            self.log(f'Модель не определила время реплик на участке {absolute / 16000:.1f}–'
                     f'{end / 16000:.1f} сек; участок сохранён как нераспознанный, запись продолжается.')
            return [], [entry]
        record('speech_timestamps_recovery_started', job_id=self.job_id, stage='speech',
               device=self.plan['backends'][self.active]['device'], reason='invalid_timestamps',
               status='running')
        base = absolute - first
        cut = middle - base
        items, failed = [], []
        for child_first, child_last in ((first, cut), (cut, last)):
            child_absolute = absolute + child_first - first
            child = directory / f'w{child_absolute:010d}-{child_absolute + child_last - child_first:010d}'
            child.mkdir(exist_ok=True)
            if not self.has_speech(child, raw, child_first, child_last, child_absolute):
                continue
            child_items, child_failed = self.recognize(child, raw, child_first, child_last,
                                                       child_absolute, depth + 1)
            items += child_items
            failed += child_failed
        record('speech_timestamps_recovery_finished', job_id=self.job_id, stage='speech',
               device=self.plan['backends'][self.active]['device'], status='done')
        return items, failed

    def has_speech(self, directory, raw, first, last, absolute):
        """Keep silent halves out of the model; the model never sees music-only audio."""
        vad = read_json(directory / 'vad.json')
        if vad is None:
            detected = speech_regions(raw[first * 2:last * 2])
            # VAD gates requests, but its tight edges must not truncate the
            # model's context. Keep silence/music-only blocks out of Whisper.
            vad = {'policy': 'full-context-v1', 'speech_regions': detected,
                   'regions': [[0, last - first]] if detected else []}
            write_json(directory / 'vad.json', vad)
        if not vad['regions']:
            self.log(f'Речь не обнаружена: пропускаем {absolute / 16000:.1f}–'
                     f'{(absolute + last - first) / 16000:.1f} сек; модель распознавания не вызываем.')
            return False
        return True


def transcribe(audio, folder, on_chunk, log, plan, job_id, language='auto', on_unresolved=None):
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
    session = requests.Session()
    session.trust_env = False
    try:
        with wave.open(str(audio), 'rb') as stream:
            if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
                raise ValueError('Нужен mono PCM16 WAV 16000 Гц')
            total = stream.getnframes()
            transcriber = _Transcriber(session, plan, state, state_file, job_id, language, log, on_chunk,
                                      on_unresolved)
            transcriber.total = total
            offset = 0
            while offset < total:
                count = min(BLOCK_FRAMES, total - offset)
                completed = [p.parent for prefix in ('local', 'local-context')
                             for p in folder.glob(f'{prefix}-{offset:010d}-*/complete.json')]
                completed = [p for p in completed
                             if 0 < int(p.name.rsplit('-', 1)[1]) <= min(BLOCK_FRAMES, total - offset)]
                previous_part = (max(completed, key=lambda p: int(p.name.rsplit('-', 1)[1]))
                                 if completed else None)
                if previous_part:
                    count = int(previous_part.name.rsplit('-', 1)[1])
                stream.setpos(offset)
                raw = stream.readframes(count)
                part = previous_part or folder / f'local-context-{offset:010d}-{count:08d}'
                part.mkdir(exist_ok=True)
                transcriber.budget = InvocationBudget()
                vad = read_json(part / 'vad.json')
                if vad is None:
                    detected = speech_regions(raw)
                    # VAD gates requests, but its tight edges must not truncate the
                    # model's context. Keep silence/music-only blocks out of Whisper.
                    vad = {'policy': 'full-context-v1', 'speech_regions': detected,
                           'regions': [[0, count]] if detected else []}
                    write_json(part / 'vad.json', vad)
                if not vad['regions']:
                    log(f'Речь не обнаружена: пропускаем {offset / 16000:.1f}–{(offset + count) / 16000:.1f} сек; '
                        'модель распознавания не вызываем.')
                for index, (first, last) in enumerate(vad['regions']):
                    region = part / f'speech-{index:04d}'
                    region.mkdir(exist_ok=True)
                    items, _ = transcriber.recognize(region, raw, first, last, offset + first, 0)
                    transcriber.publish(items, (offset + last) / 16000)
                write_json(part / 'complete.json', {'frames': count})
                transcriber.publish([], (offset + count) / 16000)
                offset += count
        return transcriber.result, 'segment'
    finally:
        session.close()
