"""Refuse code replacement/removal while this installation has running processes."""
import sys
from pathlib import Path

import psutil


def busy(root):
    root = Path(root).resolve()
    found = []
    parents = {p.pid for p in psutil.Process().parents()}
    for process in psutil.process_iter(['pid', 'exe', 'cmdline']):
        if process.pid == psutil.Process().pid or process.pid in parents:
            continue
        try:
            paths = [process.info['exe'], *(process.info['cmdline'] or [])]
            for value in paths:
                candidate = Path(value) if value else None
                # Reject foreign/UNC paths lexically before resolving; never probe other apps' network paths.
                if candidate and candidate.is_absolute() and candidate.is_relative_to(root) and candidate.resolve().is_relative_to(root):
                    found.append(process.pid)
                    break
        except (OSError, ValueError, psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


if __name__ == '__main__':
    running = busy(Path(__file__).resolve().parent.parent)
    if running:
        print('Close this installation before upgrade/uninstall. Running PIDs:', *running)
        sys.exit(64)
