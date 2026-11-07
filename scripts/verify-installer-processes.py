"""Exercise consent-gated setup cleanup on disposable embedded-Python processes."""
import argparse
import importlib.util
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('lifecycle', root / 'windows-app/release_lifecycle.py')
    lifecycle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lifecycle)
    with tempfile.TemporaryDirectory(prefix='vd-setup-processes-') as temp:
        installation = Path(temp) / 'Installation с пробелами'
        runtime = installation / 'python'
        runtime.mkdir(parents=True)
        for name in ('python.exe', 'python312.dll', 'python3.dll', 'python312.zip'):
            shutil.copyfile(args.runtime / name, runtime / name)
        (runtime / 'python312._pth').write_text('python312.zip\n.\n', encoding='ascii')
        worker = installation / 'windows-app/whisper_worker.py'
        worker.parent.mkdir()
        worker.write_text('import time\ntime.sleep(120)\n', encoding='utf-8')
        command = [str(runtime / 'python.exe'), str(worker)]
        # The launcher exits, leaving exactly the kind of orphan that blocked setup.
        launcher = subprocess.run(
            [str(runtime / 'python.exe'), '-c',
             'import subprocess,json; p=subprocess.Popen(' + repr(command)
             + ',creationflags=0x08000000); print(json.dumps(p.pid))'],
            capture_output=True, text=True, check=True, timeout=15, creationflags=0x08000000)
        pid = json.loads(launcher.stdout)
        orphan = lifecycle.psutil.Process(pid)
        # External executable with an installation path in argv must never be terminated.
        import sys
        external = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(120)', str(worker)],
                                    creationflags=0x08000000)
        try:
            time.sleep(.2)
            recorded = lifecycle.snapshot(installation)
            assert any(p['pid'] == pid and p['owned'] for p in recorded['processes'])
            assert orphan.is_running(), 'Check-only must not terminate anything'
            assert any(p['pid'] == external.pid and not p['owned'] for p in recorded['processes'])
            try:
                lifecycle.stop_confirmed(installation, recorded)
            except ValueError:
                pass
            else:
                raise AssertionError('External executable was accepted for termination')
            assert orphan.is_running() and external.poll() is None
            external.terminate()
            external.wait(timeout=10)
            recorded = lifecycle.snapshot(installation)
            assert lifecycle.stop_confirmed(installation, recorded)
            assert not lifecycle.busy(installation)
            assert not lifecycle.psutil.pid_exists(pid)
        finally:
            if external.poll() is None:
                external.terminate()
                external.wait(timeout=10)
            if lifecycle.psutil.pid_exists(pid):
                orphan.terminate()
                orphan.wait(timeout=10)
    report = {'status': 'PASS', 'scope': 'Disposable real Windows processes; no user services stopped',
              'checks': ['check-only preserves orphan', 'external Python referencing installation is refused',
                         'all identities checked before termination', 'confirmed orphan terminated',
                         'installation unblocked', 'Unicode installation path'],
              'installer_dialog_clicked': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
