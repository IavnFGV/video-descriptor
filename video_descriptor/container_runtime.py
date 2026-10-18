"""Supervise the existing HTTP server and file worker in one Linux container."""
import argparse
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    options = parser.parse_args()
    root = Path.cwd().resolve()
    for name in ('data/uploads', 'output/jobs', '.devcontainer', 'cache'):
        (root / name).mkdir(parents=True, exist_ok=True)
    os.environ['VIDEO_DESCRIPTOR_MANAGED_WORKER'] = '1'
    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopping.set())
    children = []
    result = 0
    try:
        for module, args in (
            ('video_descriptor.jobs', [str(root)]),
            ('video_descriptor.serve', ['--directory', str(root), '--bind', '0.0.0.0',
                                        '--port', str(options.port)]),
        ):
            children.append(subprocess.Popen(
                [sys.executable, '-u', '-m', module, *args], start_new_session=True))
        print('Video Descriptor: http://localhost:8000/create; diagnostics: /api/diagnostics', flush=True)
        while not stopping.wait(.5):
            if any(child.poll() is not None for child in children):
                print('Server or worker exited; stopping container for restart.', flush=True)
                result = 1
                break
    finally:
        # Groups also contain the worker's processing subprocesses and FFmpeg.
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for child in children:
                try:
                    os.killpg(child.pid, sig)
                except ProcessLookupError:
                    pass
            for child in children:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
    return result


if __name__ == '__main__':
    raise SystemExit(main())
