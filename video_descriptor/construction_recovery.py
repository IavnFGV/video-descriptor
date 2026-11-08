"""Explicit manual recovery of saved notes, without calling a model."""

import hashlib
import json

from .construction import material, parsed_notes
from .editor import EditConflict
from .jobs import jobs_dir, read_json, write_json
from .models import Source
from .platform_support import lock_file
from .versions import checked_version


def recovery_state(folder):
    result, _, frames = material(folder, read_json(folder / 'construction-settings.json', {}))
    sources = [Source(id=row.get('id', f's{index}'), start=row['start'], end=row['end'], text=row['text'])
               for index, row in enumerate(result['segments'], 1)] + [Source.model_validate(f) for f in frames]
    raw = (folder / 'construction-result.md').read_text(encoding='utf-8')
    source_revision = hashlib.sha256(json.dumps([raw, [s.model_dump() for s in sources]],
                                               sort_keys=True).encode()).hexdigest()
    manual = read_json(folder / 'construction-manual.json', {})
    text = manual.get('text', raw)
    revision = hashlib.sha256((source_revision + text).encode()).hexdigest()
    return {'text': text, 'revision': revision, 'source_revision': source_revision,
            'anchors': [{'time': int(s.start), 'text': s.text} for s in sources]}, sources, result


def recover(root, value):
    with (root / 'output/postprocess.lock').open('a+') as lock:
        lock_file(lock)
        folder, related = checked_version(root, value.get('folder'))
        failed = [(path, job) for path, job in related if job.get('status') == 'error'
                  and (job.get('task') == 'notes' or job.get('mode') == 'notes')]
        if len(failed) != 1 or (folder / 'notes.user.md').exists():
            raise ValueError('Ручное восстановление доступно для конспекта с ошибкой обработки')
        if read_json(folder / 'construction-settings.json', {}).get('result_kind') == 'article':
            raise ValueError('Ручное восстановление таймкодов доступно для конспекта')
        state, sources, _ = recovery_state(folder)
        if 'text' not in value:
            return state
        text = value['text']
        if not isinstance(text, str) or not text.strip() or len(text) > 400_000:
            raise ValueError('Введите конспект размером до 400 000 символов')
        if value.get('revision') != state['revision']:
            raise EditConflict('Ответ или расшифровка изменились. Сохраните свой текст и откройте исправление заново')
        parsed_notes(text, sources)
        write_json(folder / 'construction-manual.json',
                   {'text': text, 'source_revision': state['source_revision']})
        path, job = failed[0]
        assert path.parent.parent == jobs_dir(root)
        (path.parent / 'stop-request.json').unlink(missing_ok=True)
        job.pop('cancelled', None)
        job.pop('finished', None)
        job.update(status='queued', error=None)
        write_json(path, job)
        return {'job': job}
