"""Editable project prompts used at request boundaries."""

import json
from importlib.resources import files
from pathlib import Path

from .jobs import write_json

TASKS = {
    'summarize': ('Конспект лекции', 'lecture_notes_ru.txt'),
    'filter': ('Фильтрация конспекта', 'filter_notes_ru.txt'),
    'route': ('Выбор кадров', 'route_vision_ru.txt'),
    'quiz_explanation': ('Объяснение вопросов', 'quiz_explanation_ru.txt'),
    'translate': ('Перевод субтитров', 'translate_markers_ru.txt'),
}


def defaults():
    return {task: files('video_descriptor').joinpath('prompts', filename).read_text(encoding='utf-8')
            for task, (_, filename) in TASKS.items()}


def overrides(root=None):
    path = (Path(root) if root is not None else Path.cwd()) / '.devcontainer' / 'model-prompts.json'
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return {task: text for task, text in value.items()
            if task in TASKS and isinstance(text, str) and text.strip()} if isinstance(value, dict) else {}


def public(root):
    base = defaults()
    return {'prompts': {**base, **overrides(root)}, 'defaults': base,
            'titles': {task: title for task, (title, _) in TASKS.items()}}


def save(root, changes):
    if not isinstance(changes, dict) or changes.get('task') not in TASKS:
        raise ValueError('Выберите задачу')
    text = changes.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > 50_000:
        raise ValueError('Промпт должен содержать от 1 до 50 000 символов')
    custom = overrides(root)
    task = changes['task']
    if text == defaults()[task]:
        custom.pop(task, None)
    else:
        custom[task] = text
    path = Path(root) / '.devcontainer' / 'model-prompts.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, custom)
    return public(root)


def effective(task, fallback, log=None):
    custom = getattr(log, 'prompt_settings', None)
    return (custom if custom is not None else overrides()).get(task, fallback)
