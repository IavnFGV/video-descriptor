"""Guard replacement; stop an identified installation only after installer consent."""
import argparse
import json
import re
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
            executable = process.info['exe']
            command = process.info['cmdline'] or []
            name = Path(executable or (command[0] if command else '')).name.lower()
            # Opening a recording or folder in an editor/shell is not execution
            # of this installation. Foreign interpreters running its code still
            # block replacement, but setup must never terminate them.
            suffixes = ()
            if re.fullmatch(r'(?:python(?:w|[0-9.]*)?|pypy[0-9.]*)(?:\.exe)?', name):
                suffixes = ('.py', '.pyw')
            elif name in {'powershell.exe', 'powershell', 'pwsh.exe', 'pwsh'}:
                suffixes = ('.ps1',)
            elif name in {'cmd.exe', 'cmd'}:
                suffixes = ('.cmd', '.bat')
            paths = [executable, *(arg for arg in command if suffixes and arg.lower().endswith(suffixes))]
            for value in paths:
                candidate = Path(value) if value else None
                # Reject foreign/UNC paths lexically before resolving; never probe other apps' network paths.
                if candidate and candidate.is_absolute() and candidate.is_relative_to(root) and candidate.resolve().is_relative_to(root):
                    found.append(process.pid)
                    break
        except (OSError, ValueError, psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def local_executable(root, executable):
    path = Path(executable) if executable else None
    return bool(path and path.is_absolute() and path.is_relative_to(root)
                and path.resolve().is_relative_to(root))


def snapshot(root):
    """Record identities before consent; never treat an argument as executable ownership."""
    root = Path(root).resolve()
    entries = []
    for pid in busy(root):
        try:
            process = psutil.Process(pid)
            executable = process.exe()
            script = next((Path(arg).name for arg in process.cmdline()
                           if arg.endswith('.py') and local_executable(root, arg)), '')
            entries.append({'pid': pid, 'created': process.create_time(), 'exe': executable,
                            'name': (script + ' / ' if script else '') + Path(executable).name,
                            'owned': local_executable(root, executable)})
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            entries.append({'pid': pid, 'name': 'access denied', 'owned': False})
    return {'root': str(root), 'processes': entries}


def stop_confirmed(root, recorded):
    """Only terminate the exact executable/PID/birth identities shown before consent."""
    root = Path(root).resolve()
    if recorded.get('root') != str(root):
        raise ValueError('Installation changed; check running processes again')
    targets = []
    excluded = {psutil.Process().pid, *(p.pid for p in psutil.Process().parents())}
    for entry in recorded['processes']:
        if not entry['owned'] or entry['pid'] in excluded:
            raise ValueError('A process outside this installation cannot be stopped by setup')
        try:
            process = psutil.Process(entry['pid'])
            if (process.create_time() != entry['created'] or process.exe() != entry['exe']
                    or not local_executable(root, process.exe())):
                raise ValueError('Process identity changed; check running processes again')
            targets.append(process)
        except psutil.NoSuchProcess:
            continue
    # Preflight every identity before stopping any process. psutil also guards PID reuse
    # inside terminate(); descendants/external services are never stopped recursively.
    for process in targets:
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(targets, timeout=10)
    return not alive and not busy(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--stop-confirmed', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    if args.stop_confirmed:
        if not args.snapshot:
            raise ValueError('A pre-consent process snapshot is required')
        recorded = json.loads(args.snapshot.read_text(encoding='utf-8'))
        return 0 if stop_confirmed(root, recorded) else 64
    if args.snapshot:
        recorded = snapshot(root)
        args.snapshot.write_text(json.dumps(recorded), encoding='utf-8')
        if args.report:
            args.report.write_text('\r\n'.join(
                f"{p['name']} (PID {p['pid']})" for p in recorded['processes']), encoding='utf-8')
        return 64 if recorded['processes'] else 0
    running = busy(root)
    if running:
        print('Close this installation before upgrade/uninstall. Running PIDs:', *running)
        return 64
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, psutil.Error) as error:
        print('Installation remains blocked:', error)
        sys.exit(65)
