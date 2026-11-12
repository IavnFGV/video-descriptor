"""Bounded, structured local action history; never log transcript/request bodies."""
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .atomic_file import read_text
from .platform_support import lock_file

FIELDS = {'job_id', 'attempt', 'stage', 'requested', 'device', 'previous_device',
          'reason', 'model_sha256', 'status', 'format', 'language', 'route', 'code',
          'operation_id', 'request_id', 'model', 'received', 'result_kind', 'task', 'component'}


def record(action, *, path=None, folder=None, **fields):
    target = path or os.getenv('VIDEO_DESCRIPTOR_EVENTS')
    workspace = os.getenv('VIDEO_DESCRIPTOR_WORKSPACE')
    if folder is None and workspace and fields.get('job_id'):
        try:
            job = json.loads(read_text(Path(workspace) / 'output/jobs' / fields['job_id'] / 'job.json'))
            name = job.get('folder')
            if name and Path(name).name == name:
                folder = Path(workspace) / 'output' / name
        except (OSError, ValueError):
            pass
    targets = [Path(target)] if target else []
    if folder is not None:
        folder = Path(folder)
        targets.append(folder / 'application-events.jsonl')
    if not targets:
        return
    event = {'id': uuid.uuid4().hex, 'time_utc': datetime.now(UTC).isoformat(),
             'action': action, **{key: value for key, value in fields.items() if key in FIELDS}}
    if folder is not None:
        event['folder'] = folder.name
    delivered, failures = [], []
    for target in dict.fromkeys(targets):
        try:
            append_event(target, event)
            delivered.append(target)
        except OSError as exc:
            failures.append(type(exc).__name__)
    if failures:
        # A temporarily locked record journal must not abort a model request or
        # turn an already-saved edit into an apparent failure. Retain the event
        # in the other sink and report the delivery problem explicitly.
        logging.getLogger(__name__).error('Journal delivery failed: event=%s reason=%s', event['id'], ','.join(failures))
        if delivered:
            try:
                append_event(delivered[0], {'id': uuid.uuid4().hex, 'time_utc': datetime.now(UTC).isoformat(),
                                           'action': 'journal_delivery_failed', 'status': 'error',
                                           'operation_id': event['id'], 'reason': ','.join(failures)})
            except OSError:
                pass  # The same failure was already emitted to the application logger.
    return bool(delivered)


def append_event(target, event):
    """The sole structured journal writer for HTTP, workers, requests and edits."""
    target.parent.mkdir(parents=True, exist_ok=True)
    # An O_APPEND write guarded by the same cross-platform lock across app/worker processes.
    with target.with_suffix('.lock').open('a+') as lock:
        import time
        for attempt in range(50):
            try:
                lock_file(lock)
                break
            except BlockingIOError:
                if attempt == 49:
                    raise
                time.sleep(.01)
        with target.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')


def describe(event):
    labels = {'llm_request': 'Обращение к языковой модели', 'llm_verification': 'Проверка генерации', 'operation_started': 'Операция начата', 'operation_finished': 'Операция выполнена',
              'operation_failed': 'Ошибка операции', 'model_request_started': 'Запрос к модели отправлен',
              'model_request_finished': 'Запрос к модели завершён', 'progress': 'Ход обработки',
              'generation_started': 'Генерация начата', 'answer_validation': 'Проверка ответа модели',
              'result_saving': 'Сохранение результата', 'result_saved': 'Результат сохранён',
              'notes_saved': 'Правки конспекта сохранены', 'recovery_saved': 'Исправленный ответ сохранён',
              'generation_failed': 'Ошибка генерации'}
    labels.update(component_state='Состояние компонента', storage_state='Состояние хранилища')
    labels.update(transcript_edited='Правки расшифровки сохранены', speaker_names_saved='Имена участников сохранены',
                  recording_title_saved='Название записи сохранено')
    labels.update(speech_timestamps_recovery_started='Восстановление таймкодов',
                  speech_timestamps_recovery_finished='Таймкоды восстановлены',
                  speech_timestamps_unresolved='Участок без таймкодов',
                  speech_unresolved_resolved='Участок без таймкодов исправлен')
    labels['journal_delivery_failed'] = 'Не удалось обновить один из журналов'
    labels['update_check'] = 'Проверка обновлений'
    labels['update_cache'] = 'Кэш обновлений'
    labels['speech_progress_save_failed'] = 'Индикатор прогресса временно недоступен'
    labels['speech_result_save_failed'] = 'Не удалось сохранить результат распознавания'
    values = [labels.get(event['action'], event['action'])]
    for key in ('route', 'result_kind', 'stage', 'task', 'component', 'model', 'status', 'reason'):
        if event.get(key) is not None:
            value = event[key]
            if key == 'result_kind':
                value = {'article': 'статья', 'notes': 'конспект'}.get(value, value)
            values.append(str(value))
    if event.get('received') is not None:
        values.append('получено ' + str(event['received']) + ' симв.')
    if event.get('code') is not None:
        values.append('HTTP ' + str(event['code']))
    return ' · '.join(values)
