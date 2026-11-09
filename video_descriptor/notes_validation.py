"""Actionable, source-grounded diagnostics for timestamped notes."""

import re


def clock(seconds):
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


def notes_issues(text, sources):
    starts = {int(source.start): source.text for source in sources}
    boundaries = set(starts) | {int(source.end) for source in sources if source.end >= 0}
    issues = []

    def issue(code, message, start, end, section, seconds=None):
        candidates = []
        if seconds is not None:
            for value in sorted(starts, key=lambda value: (abs(value - seconds), value))[:2]:
                candidates.append({'time': clock(value), 'text': starts[value]})
        issues.append({'code': code, 'message': message, 'section': section,
                       'line': text.count('\n', 0, start) + 1,
                       # DOM selection offsets count UTF-16 code units, not Python characters.
                       'start': len(text[:start].encode('utf-16-le')) // 2,
                       'end': len(text[:end].encode('utf-16-le')) // 2,
                       'value': text[start:end], 'candidates': candidates})

    if not sources:
        issue('sources', 'Не найдены реплики исходной расшифровки. Проверьте выбранную версию речи.', 0, 0, '')
        return issues
    missing = [name for name in ['Оглавление', 'Конспект'] if '## ' + name not in text]
    if missing:
        issue('sections', 'Добавьте разделы: ' + ', '.join('## ' + name for name in missing) + '.', 0, 0, '')
        return issues
    body_at = text.index('## Конспект')
    previous = -1
    counts = {'Оглавление': 0, 'Конспект': 0}
    pattern = re.compile(r'^###\s+\[(\d{2,}:[0-5]\d:[0-5]\d)(?:\s*[-–—]\s*(\d{2,}:[0-5]\d:[0-5]\d))?\]\s+(.+)$')
    offset = 0
    for line in text.splitlines(keepends=True):
        section = 'Оглавление' if offset < body_at else 'Конспект'
        if re.match(r'^###(?:\s|$)', line):
            counts[section] += 1
            match = pattern.fullmatch(line.rstrip('\r\n'))
            if not match:
                issue('heading', 'Используйте заголовок вида ### [00:18:50] Название темы.',
                      offset, offset + len(line.rstrip('\r\n')), section)
            else:
                seconds = sum(int(part) * scale for part, scale in zip(match[1].split(':'), (3600, 60, 1), strict=True))
                if seconds not in starts:
                    issue('unknown_time', 'У этой метки нет точного совпадения с началом реплики. Выберите подтверждённую метку по тексту реплики.',
                          offset + match.start(1), offset + match.end(1), section, seconds)
                elif section == 'Оглавление' and seconds < previous:
                    issue('chronology', 'Метка идёт раньше предыдущей темы (' + clock(previous) + '). Проверьте порядок тем или выбранную реплику.',
                          offset + match.start(1), offset + match.end(1), section)
                if match[2]:
                    stop = sum(int(part) * scale for part, scale in zip(match[2].split(':'), (3600, 60, 1), strict=True))
                    if stop not in boundaries or stop <= seconds:
                        issue('range', 'Конец диапазона должен совпадать с подтверждённой границей реплики и идти после начала. Можно оставить в заголовке только начальную метку.',
                              offset + match.start(2), offset + match.end(2), section)
                if section == 'Оглавление':
                    previous = seconds
        offset += len(line)
    for section, count in counts.items():
        if not count:
            at = 0 if section == 'Оглавление' else body_at
            issue('headings', 'В разделе нужны темы с заголовками ### [ЧЧ:ММ:СС] Название.', at, at, section)
    return issues
