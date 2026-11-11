"""Adaptive recovery for unusable model timestamps.

The model occasionally answers a window with timestamps that cannot be trusted
(for example a missing end marker or a repeated hallucination). Such a window is
split into two independent halves that are transcribed separately, so a single
bad stretch never hides the rest of the recording. Subdivision stops at the
configured minimum interval; a window that still fails at that size is recorded
as unresolved and the recording continues with the next interval.

Nothing here fabricates timestamps: an unresolved interval stays outside the
transcript and carries the offending numeric values for diagnostics only.
"""

MIN_INTERVAL_SECONDS = 5
MIN_INTERVAL_FRAMES = MIN_INTERVAL_SECONDS * 16000
MAX_RECOVERY_DEPTH = 12
MAX_INTERVAL_REQUESTS = 256


class InvalidTimestamps(ValueError):
    """Model timestamps are unusable for this window; the audio never receives invented times.

    `details` keeps the offending numeric values for diagnostics; it never holds transcript text.
    """

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = dict(details or {})


class InvalidWorkerTimestamps(InvalidTimestamps):
    """The worker itself reported unusable model timestamps for the window."""


class InvocationBudget:
    """Bounds how many model calls one part may spend while recovering timestamps."""

    def __init__(self, limit=MAX_INTERVAL_REQUESTS):
        self.limit = limit
        self.used = 0

    @property
    def exhausted(self):
        return self.used >= self.limit

    def take(self):
        """Account for one model call; returns False when the budget is spent."""
        if self.exhausted:
            return False
        self.used += 1
        return True


def split_interval(start, end, minimum=MIN_INTERVAL_FRAMES):
    """Split [start, end) on the recovery grid; None when the window cannot be split.

    The cut keeps whole recovery intervals, so an unresolved range covers exactly
    the audio that could not be transcribed.
    """
    cells = (end - start) // minimum
    if cells < 2:
        return None
    return start + (cells // 2) * minimum


def unresolved_entry(start, end, reason='invalid_timestamps', detail=None):
    """Describe an interval the model could not timestamp; no transcript text is stored."""
    entry = {'id': f'u-{start:010d}-{end:010d}', 'start': round(start / 16000, 3),
             'end': round(end / 16000, 3), 'status': 'unresolved', 'reason': reason}
    if detail:
        entry['detail'] = detail
    return entry


REASON_TEXT = {
    'invalid_timestamps': 'Модель вернула непригодные таймкоды, поэтому реплики здесь не распознаны.',
    'recovery_limit': 'Участок не удалось разобрать автоматически.',
}


def clock(seconds):
    """Absolute recording time as HH:MM:SS."""
    value = int(seconds)
    return f'{value // 3600:02}:{value // 60 % 60:02}:{value % 60:02}'


def describe_unresolved(entry):
    """Russian explanation of an interval without usable timestamps."""
    reason = REASON_TEXT.get(entry.get('reason'),
                             'На этом участке нет корректных таймкодов, речь не распознана.')
    return (f'{reason} Участок {clock(entry["start"])}–{clock(entry["end"])} '
            'нужно расшифровать вручную.')


def pending_unresolved(entries, segments):
    """Intervals without usable timestamps that the user has not transcribed yet.

    A manual transcription becomes an ordinary segment carrying the interval id,
    so the interval stops being pending as soon as the user resolves it.
    """
    known = {row.get('id') for row in segments or []}
    return [{**entry, 'note': describe_unresolved(entry)}
            for entry in entries or [] if entry.get('id') not in known]
