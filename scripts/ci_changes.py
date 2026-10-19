"""Conservative path routing. No GitHub API/token or PR code execution privileges."""
import argparse
import json
import os
import subprocess
from pathlib import Path


def classify(paths):
    code = [p for p in paths if not (p.endswith('.md') or p.startswith(('docs/', 'design-system/evidence/')) or p in ('.gitignore', 'LICENSE'))]
    infrastructure = any(p in ('.github/workflows/windows-smoke.yml', 'scripts/check-installer-smoke.py') for p in code)
    windows = infrastructure or any(p.startswith(('windows-app/', 'video_descriptor/', 'design-system/'))
        or p in ('pyproject.toml',) for p in code)
    installer = any(p.startswith(('windows-app/installer', 'windows-app/Prepare-', 'windows-app/build_release',
        'windows-app/release', 'windows-app/requirements', 'windows-app/component-manifest')) for p in code)
    container = any((p.startswith('video_descriptor/') and p.endswith('.py'))
        or p.startswith(('video_descriptor/prompts/', 'docker/', 'scripts/smoke_compose'))
        or p in ('Dockerfile', '.dockerignore', 'compose.yaml', 'pyproject.toml',
                 'requirements-container.txt', 'requirements-container.lock',
                 '.github/workflows/container-smoke.yml') for p in code)
    return {'code': bool(code), 'windows': windows, 'installer': installer, 'container': container}


def changed(base, head, pull_request=False):
    if not base or set(base) == {'0'}:
        return subprocess.check_output(['git', 'ls-files', '-z']).decode().split('\0')[:-1]
    if pull_request:
        base = subprocess.check_output(['git', 'merge-base', base, head], text=True).strip()
    # A move out of a critical directory must include the deletion, not just the new name.
    return subprocess.check_output(['git', 'diff', '--no-renames', '--name-only', '-z', base, head]).decode().split('\0')[:-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--head', required=True)
    args = parser.parse_args()
    result = classify(changed(args.base, args.head, os.environ.get('GITHUB_EVENT_NAME') == 'pull_request'))
    print(json.dumps(result))
    if os.environ.get('GITHUB_OUTPUT'):
        with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
            output.writelines(f'{key}={str(value).lower()}\n' for key, value in result.items())


if __name__ == '__main__':
    main()
