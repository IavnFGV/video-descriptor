"""One fresh install/health/uninstall smoke, with no models or lifecycle upgrade fixture."""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows-app'))
from verify_release import require_no_registered_install, smoke


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('installer', type=Path)
    args = parser.parse_args()
    require_no_registered_install()
    root = Path(tempfile.mkdtemp(prefix='vd-install-smoke-')) / 'Installed app'
    try:
        subprocess.run([str(args.installer.resolve()), '/VERYSILENT', '/SUPPRESSMSGBOXES',
            '/NORESTART', '/SP-', '/TASKS=', '/NOICONS', '/DIR=' + str(root)], check=True, timeout=300)
        result = smoke(root)
        print(json.dumps(result))
    finally:
        uninstaller = root / 'unins000.exe'
        if uninstaller.exists():
            subprocess.run([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'],
                           check=True, timeout=180)


if __name__ == '__main__':
    main()
