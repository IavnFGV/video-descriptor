"""Public, measured per-stage progress; contains no audio, embeddings or speaker guesses."""
import math
import time

LABELS = {
    'audio': 'Подготавливаем аудио',
    'model_load': 'Загружаем локальную модель',
    'segmentation': 'Ищем речь и смены голосов',
    'speaker_counting': 'Анализируем речевые участки',
    'embeddings': 'Сравниваем голоса',
    'clustering': 'Объединяем одинаковые голоса',
    'assignment': 'Назначаем участников репликам',
    'saving': 'Сохраняем результат',
    'complete': 'Реплики разделены по участникам',
}


def progress_state(stage, previous=None, completed=None, total=None, at=None):
    previous = previous if isinstance(previous, dict) else {}
    stamp = time.time() if at is None else at
    value = {'stage': stage, 'label': LABELS.get(stage, 'Разделяем реплики по участникам'),
             'updated_at': stamp, 'stage_started_at': previous.get('stage_started_at', stamp)
             if previous.get('stage') == stage else stamp}
    if (type(total) in (int, float) and math.isfinite(total) and total > 0
            and type(completed) in (int, float) and math.isfinite(completed) and 0 <= completed <= total):
        value.update(completed=completed, total=total)
    return value
