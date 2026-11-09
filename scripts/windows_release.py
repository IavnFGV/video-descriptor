"""Publish only accepted standard Windows assets; never rebuild or upload Domestic."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def bump_build(path):
    number = int(path.read_text(encoding='ascii').strip())
    if number < 0:
        raise ValueError('BUILD must contain a non-negative integer')
    path.write_text(str(number + 1) + '\n', encoding='ascii')
    return number + 1


def prepare():
    if os.getenv('GITHUB_REF') != 'refs/heads/main':
        raise ValueError('Prepare a new release only from main')
    version = json.loads((ROOT / 'windows-app/release-inputs.json').read_text(encoding='utf-8'))['version']
    tag = validate_ref('refs/tags/v' + version, version)
    if not (ROOT / 'docs/releases' / (version + '.md')).is_file():
        raise ValueError('Write version-specific release notes before preparing a release')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    main = subprocess.check_output(['git', 'rev-parse', 'origin/main'], cwd=ROOT, text=True).strip()
    if head != main:
        raise ValueError('main changed; restart preparation at the current main revision')
    exists = subprocess.run(['git', 'show-ref', '--verify', '--quiet', 'refs/tags/' + tag], cwd=ROOT, check=False)
    if exists.returncode == 0:
        raise ValueError('Version tag already exists; retry its workflow without incrementing BUILD')
    if exists.returncode != 1:
        raise RuntimeError('Cannot inspect existing release tags')
    number = bump_build(ROOT / 'BUILD')
    for args in [['config', 'user.name', 'github-actions[bot]'],
                 ['config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'],
                 ['add', 'BUILD'], ['commit', '-m', f'Prepare {tag}, build {number}'],
                 ['tag', '-a', tag, '-m', f'Video Descriptor {version}, build {number}'],
                 ['push', '--atomic', 'origin', 'HEAD:main', 'refs/tags/' + tag]]:
        subprocess.run(['git', *args], cwd=ROOT, check=True)
    gh('workflow', 'run', 'windows-release.yml', '--ref', tag)


def validate_ref(ref, version):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or ref != 'refs/tags/v' + version:
        raise ValueError('Select the existing v' + version + ' tag; branch/manual releases are not allowed')
    return 'v' + version


def validate():
    version = json.loads((ROOT / 'windows-app/release-inputs.json').read_text(encoding='utf-8'))['version']
    tag = validate_ref(os.getenv('GITHUB_REF', ''), version)
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    tagged = subprocess.check_output(['git', 'rev-parse', 'refs/tags/' + tag + '^{commit}'], cwd=ROOT, text=True).strip()
    if tagged != sha:
        raise ValueError('Checked-out revision differs from the release tag')
    subprocess.run(['git', 'merge-base', '--is-ancestor', sha, 'origin/main'], cwd=ROOT, check=True)
    number = int((ROOT / 'BUILD').read_text(encoding='ascii').strip())
    previous = []
    tags = subprocess.check_output(['git', 'tag', '--merged', 'HEAD', '--list', 'v*'], cwd=ROOT, text=True).splitlines()
    for older in tags:
        if older == tag or not re.fullmatch(r'v\d+\.\d+\.\d+', older):
            continue
        try:
            value = subprocess.check_output(['git', 'show', older + ':BUILD'], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
            previous.append(int(value.strip()))
        except subprocess.CalledProcessError:
            continue  # Older versions predate the tracked BUILD file.
    if number < 1 or (previous and number <= max(previous)):
        raise ValueError('Increment BUILD before tagging a new release; retries must use the same tag')
    return tag, version, sha


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def gh(*args):
    return subprocess.run(['gh', *map(str, args)], cwd=ROOT, check=True)


def publish(directory, tag, version, sha):
    subprocess.run([sys.executable, str(ROOT / 'scripts/ci_artifacts.py'), '--directory', str(directory)],
                   cwd=ROOT, check=True)
    names = [f'VideoDescriptor-{version}-windows-x64-setup.exe', f'VideoDescriptor-{version}-windows-x64.zip',
             'SHA256SUMS.json', 'acceptance-provenance.json']
    paths = {name: directory / name for name in names}
    for path in paths.values():
        if not path.is_file() or path.stat().st_size >= 2**31:
            raise ValueError('Missing release file or asset exceeds GitHub limit: ' + path.name)
    notes = ROOT / 'docs/releases' / (version + '.md')
    if not notes.is_file():
        raise ValueError('Write version-specific release notes before publication')
    number = int((ROOT / 'BUILD').read_text(encoding='ascii').strip())
    current = subprocess.run(['gh', 'release', 'view', tag, '--json', 'isDraft,assets'], cwd=ROOT,
                             capture_output=True, text=True, check=False)
    if current.returncode:
        if 'release not found' not in current.stderr.lower():
            raise RuntimeError('Cannot inspect GitHub release; publication stopped')
        gh('release', 'create', tag, '--verify-tag', '--target', sha, '--draft',
           '--title', f'Video Descriptor {tag} (build {number})', '--notes-file', notes)
        state = {'isDraft': True, 'assets': []}
    else:
        state = json.loads(current.stdout)
    existing = {item['name'] for item in state['assets']}
    if existing - set(names):
        raise ValueError('Existing release contains unexpected assets; nothing will be overwritten')
    missing = set(names) - existing
    if missing and not state['isDraft']:
        raise ValueError('Published release is incomplete; refusing to modify published assets')
    if missing:
        gh('release', 'upload', tag, *(paths[name] for name in names if name in missing))
    # Verify what users will download, including metadata, before exposing a draft.
    with tempfile.TemporaryDirectory(prefix='vd-release-download-') as temporary:
        command = ['release', 'download', tag, '--dir', temporary]
        for name in names:
            command.extend(['--pattern', name])
        gh(*command)
        for name, path in paths.items():
            if digest(Path(temporary) / name) != digest(path):
                raise ValueError('GitHub asset differs from accepted bytes: ' + name)
    if state['isDraft']:
        gh('release', 'edit', tag, '--notes-file', notes, '--draft=false', '--latest')
    print('Verified Windows release:', tag, sha)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'validate', 'publish'])
    parser.add_argument('--directory', type=Path, default=Path('accepted-windows'))
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
        return
    tag, version, sha = validate()
    if args.action == 'publish':
        publish(args.directory.resolve(), tag, version, sha)


if __name__ == '__main__':
    main()
