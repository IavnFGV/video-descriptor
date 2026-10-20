"""Small OS adapters shared by the queue and the native Windows launcher."""
import os
from pathlib import Path


def lock_file(stream):
    """Acquire a nonblocking lock held until the stream is closed."""
    if os.name == 'nt':
        import msvcrt
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write('0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError('Другой экземпляр уже работает') from exc
    else:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)


def windows_processes():
    """Inspect process arguments without invoking PowerShell on each UI poll."""
    import psutil
    for process in psutil.process_iter(['pid', 'cmdline', 'cwd']):
        try:
            if process.pid != os.getpid():
                yield process.info.get('cmdline') or [], Path(process.info.get('cwd') or '.')
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue


def environment_python(root, name):
    override = os.getenv('VIDEO_DESCRIPTOR_DIARIZATION_PYTHON')
    return Path(override) if override else root / name / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def subprocess_options():
    return {'creationflags': 0x08000000} if os.name == 'nt' else {'start_new_session': True}



def windows_powershell():
    """Windows inbox shell, independent of PATH or a parent PowerShell 7 install."""
    return str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe')


def windows_shell_environment(extra=None):
    # PowerShell 7's module path can make Windows PowerShell load incompatible DLLs.
    return {**{key: value for key, value in os.environ.items() if key.upper() != 'PSMODULEPATH'}, **(extra or {})}
