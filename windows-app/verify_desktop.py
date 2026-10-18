"""Isolated real WebView2 smoke; does not load models or stop host services."""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import build_release
from verify_release import configure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', type=Path, help='Verify the packaged EXE with its bundled Python')
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('Real WebView2 smoke requires Windows and WebView2 Runtime')
    here = Path(__file__).resolve().parent
    root = Path(tempfile.mkdtemp(prefix='desktop-smoke-', dir=here / 'runtime'))
    if args.zip:
        with zipfile.ZipFile(args.zip) as archive:
            for name in archive.namelist():
                build_release.safe_member(name)
            archive.extractall(root)
        python = root / 'python/python.exe'
    else:
        for source in build_release.source_paths():
            target = root / source.relative_to(here.parent)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        shutil.copytree(here / 'runtime/desktop-sdk', root / 'windows-app/desktop-sdk')
        python = Path(sys.executable)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    configure(root, port)
    command = [str(root / 'windows-app/desktop-sdk/VideoDescriptor.exe'),
               str(root / 'windows-app'), str(python), '--smoke']
    result = None
    try:
        result = subprocess.run(command, check=False, capture_output=True, encoding='utf-8',
                                errors='replace', timeout=90)
        if result.returncode:
            error = root / 'windows-app/runtime/desktop-smoke-error.txt'
            raise RuntimeError(error.read_text(encoding='utf-8') if error.exists() else result.stdout + result.stderr)
    finally:
        stopped = subprocess.run([str(python), '-X', 'utf8', str(root / 'windows-app/app.py'), '--stop'],
                                 check=False, capture_output=True, timeout=10)
        report = {'passed': result is not None and result.returncode == 0 and stopped.returncode == 0,
                  'checks': ['real WebView2 initialization', 'existing UI DOM loaded', 'AI setup DOM and JavaScript handlers loaded',
                             'active queue rejects shutdown', 'close hides window without disposal',
                             'backend identity after close', 'second launch restores the same window',
                             'backend loss displays error', 'retry reconnects and restores WebView'],
                  'isolated_installation': str(root), 'packaged_python': bool(args.zip),
                  'backend_stop_exit': stopped.returncode}
        (here.parent / 'dist').mkdir(exist_ok=True)
        (here.parent / 'dist/verification-desktop.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    assert report['passed'], report
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
