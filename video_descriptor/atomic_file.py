"""Atomic publication of artifacts under Windows sharing rules.

Windows refuses to rename a file over an open one, and its atomic replacement
API succeeds only when every reader allowed deletion. Artifacts are therefore
read with FILE_SHARE_DELETE and published with ReplaceFileW. Holders that do
not share deletion (antivirus, file browsers) are waited out instead of
failing the operation that publishes a result.
"""

import json
import os
import tempfile
import time
from contextlib import suppress
from pathlib import Path

ATTEMPTS = 6
RESULT_ATTEMPTS = 20
BACKOFF = 0.01
MAX_BACKOFF = 0.1
REPLACEFILE_IGNORE_MERGE_ERRORS = 0x2
# ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION,
# ERROR_UNABLE_TO_REMOVE_REPLACED, ERROR_UNABLE_TO_MOVE_REPLACEMENT
RETRYABLE_WINERRORS = frozenset({5, 32, 33, 1175, 1176})


def retryable(exc):
    """Tell a transient Windows sharing conflict from a permanent failure."""
    if isinstance(exc, PermissionError):
        return True
    return getattr(exc, 'winerror', None) in RETRYABLE_WINERRORS


def _windows_shared_handle(path):
    """Open a file for reading so that a publisher may replace it."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
    handle = kernel.CreateFileW(str(path), 0x80000000, 0x1 | 0x2 | 0x4, None, 3, 0x80, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    import msvcrt
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except OSError:
        kernel.CloseHandle(handle)
        raise
    return os.fdopen(descriptor, 'r', encoding='utf-8')


def open_shared(path):
    """Open a file for reading without blocking a concurrent publication."""
    path = Path(path)
    if os.name == 'nt':
        try:
            return _windows_shared_handle(path)
        except OSError:
            pass
    return open(path, 'r', encoding='utf-8')


def read_text(path):
    """Read text; a concurrent publisher may replace the file meanwhile."""
    with open_shared(path) as stream:
        return stream.read()


def _windows_replace(target, source):
    """Replace target with source through the atomic Windows API."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.ReplaceFileW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                    wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID]
    kernel.ReplaceFileW.restype = wintypes.BOOL
    if not kernel.ReplaceFileW(str(target), str(source), None, REPLACEFILE_IGNORE_MERGE_ERRORS, None, None):
        raise ctypes.WinError(ctypes.get_last_error())


def _swap(source, target):
    """Publish source as target with a single atomic step."""
    if os.name == 'nt':
        try:
            _windows_replace(target, source)
            return
        except FileNotFoundError:
            pass  # A new artifact is published by renaming it into place.
    os.replace(source, target)


def replace(source, target, attempts=ATTEMPTS):
    """Publish source as target; wait out transient Windows sharing locks."""
    if attempts < 1:
        raise ValueError('A publication needs at least one attempt')
    for attempt in range(attempts):
        try:
            _swap(source, target)
            return
        except OSError as exc:
            if attempt + 1 >= attempts or not retryable(exc):
                raise
            time.sleep(min(BACKOFF * 2 ** attempt, MAX_BACKOFF))


def write_text(path, text, attempts=ATTEMPTS):
    """Publish text through a unique temporary file and an atomic replacement."""
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.name}.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        replace(temporary, path, attempts)
        temporary = None
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def write_json(path, value, attempts=ATTEMPTS):
    """Publish a JSON artifact atomically."""
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2), attempts)
