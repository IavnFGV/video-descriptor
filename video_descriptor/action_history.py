"""Bounded, structured local action history; never log transcript/request bodies."""
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .platform_support import lock_file

FIELDS = {'job_id', 'attempt', 'stage', 'requested', 'device', 'previous_device',
          'reason', 'model_sha256', 'status', 'format', 'language'}


def record(action, *, path=None, **fields):
    target = path or os.getenv('VIDEO_DESCRIPTOR_EVENTS')
    if not target:
        return
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    event = {'id': uuid.uuid4().hex, 'time_utc': datetime.now(UTC).isoformat(),
             'action': action, **{key: value for key, value in fields.items() if key in FIELDS}}
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
