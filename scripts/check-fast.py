"""Local/CI entry point. Uses installed dev dependencies; never installs AI components."""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require_windows_dev_environment(root, prefix, platform, github_actions):
    """Local Windows checks use this checkout's venv; GitHub uses its locked runner Python."""
    if platform != 'win32' or github_actions == 'true':
        return
    venv = root / '.venv'
    if Path(prefix).resolve() != venv.resolve() or not (venv / 'Scripts/python.exe').is_file():
        raise SystemExit(
            'Use the project Windows environment: .\\.venv\\Scripts\\python.exe scripts/check-fast.py '
            '(with the same arguments). Create/populate .venv from the project requirements if missing; '
            'the check does not install dependencies.'
        )


def run(*command):
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit-only', action='store_true', help='Windows OS-specific suite without repeated static checks')
    parser.add_argument('--config-only', action='store_true', help='Documentation-only CI: workflow contracts and syntax')
    parser.add_argument('--skip-config', action='store_true', help='CI routing job already checked configuration')
    args = parser.parse_args()
    require_windows_dev_environment(ROOT, sys.prefix, sys.platform, os.environ.get('GITHUB_ACTIONS'))
    os.environ.update(PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      PYTHONDONTWRITEBYTECODE='1')
    sys.dont_write_bytecode = True
    if not args.unit_only and not args.skip_config:
        run(sys.executable, 'scripts/check-actions.py')
        run(sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests/test_ci_policy.py')
    if args.config_only:
        return
    if not args.unit_only:
        run(sys.executable, '-m', 'ruff', 'check', '--no-cache', 'video_descriptor', 'tests', 'windows-app',
            'scripts/check-fast.py', 'scripts/check-actions.py', 'scripts/ci_changes.py',
            'scripts/ci_artifacts.py', 'scripts/check-installer-smoke.py',
            'scripts/smoke_compose.py', 'scripts/whisper_npu_server.py',
            'scripts/local_build.py', 'scripts/run_dev.py', 'scripts/clean_local.py', 'scripts/download_build_file.py',
            'scripts/windows_release.py', 'scripts/evaluate_models.py')
        run(sys.executable, 'scripts/check-ui-audit.py')  # includes CSS consistency once
        node = shutil.which('node')
        if not node:
            raise SystemExit('Node.js is required for JavaScript syntax checks; no checks silently skipped.')
        for folder in ('windows-app/ui', 'video_descriptor/assets'):
            for path in sorted((ROOT / folder).glob('*.js')):
                run(node, '--check', str(path))
    run(sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--ignore=tests/test_ci_policy.py')


if __name__ == '__main__':
    main()
