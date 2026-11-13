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
NOTES_DIRECTORY = 'docs/releases'
NEXT_NOTES = 'next-build.md'
NOTES_PLACEHOLDER = 'NEXT-BUILD-PLACEHOLDER'
MINIMUM_NOTES_LENGTH = 40


def build_label(build):
    number = int(build)
    return f'{number:04d}' if number >= 12 else str(number)


def product_version():
    return json.loads((ROOT / 'windows-app/release-inputs.json').read_text(encoding='utf-8'))['version']


def next_notes_path():
    return ROOT / NOTES_DIRECTORY / NEXT_NOTES


def build_notes_name(version, build):
    return f'{version}-build.{build_label(build)}.md'


def notes_problems(text):
    """Reasons why the text cannot be published as release notes."""
    stripped = text.strip()
    if not stripped:
        return ['release notes are empty']
    if NOTES_PLACEHOLDER in text:
        return ['release notes still contain the template placeholder']
    if 'TODO' in text:
        return ['release notes still contain TODO markers']
    if not any(line.lstrip().startswith('#') for line in stripped.splitlines()):
        return ['release notes need a Markdown heading']
    body = [line.strip() for line in stripped.splitlines()
            if line.strip() and not line.strip().startswith('#') and not line.strip().startswith('<!--')]
    if not any(len(line) >= 10 for line in body):
        return ['release notes need at least one descriptive line']
    if len(stripped) < MINIMUM_NOTES_LENGTH:
        return [f'release notes need at least {MINIMUM_NOTES_LENGTH} characters']
    return []


def next_notes_template(version, build):
    return (f'# Video Descriptor {version} — сборка {build_label(build)}\n'
            '\n'
            f'<!-- {NOTES_PLACEHOLDER}: замените шаблон описанием изменений сборки -->\n'
            '\n'
            '## Что изменилось\n'
            '\n'
            '- TODO: перечислите изменения этой сборки.\n'
            '\n'
            '## Проверки и ограничения\n'
            '\n'
            '- TODO: укажите пройденные проверки и известные ограничения.\n')


def bump_build(path):
    number = int(path.read_text(encoding='ascii').strip())
    if number < 0:
        raise ValueError('BUILD must contain a non-negative integer')
    path.write_text(build_label(number + 1) + '\n', encoding='ascii')
    return number + 1


def git_text(revision, path):
    """Exact file content of a revision, or None when that revision has no such path."""
    try:
        data = subprocess.check_output(['git', 'show', f'{revision}:{path}'], cwd=ROOT, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as error:
        message = (error.stderr or b'').decode('utf-8', 'replace').lower()
        if 'does not exist' in message or 'exists on disk' in message or 'not a valid object name' in message:
            return None
        raise RuntimeError(f'Cannot read {path} from {revision}') from error
    return data


def notes_candidates(tag):
    """Release notes paths of a tag: the build notes first, then the legacy version notes."""
    match = re.fullmatch(r'v(\d+\.\d+\.\d+)(?:-build\.(\d+))?', tag)
    if not match:
        raise ValueError('Select an existing release tag')
    version, build = match[1], match[2]
    candidates = []
    if build:
        candidates.append(f'{NOTES_DIRECTORY}/{version}-build.{build}.md')
    candidates.append(f'{NOTES_DIRECTORY}/{version}.md')
    return candidates


def release_notes(tag):
    """Release notes recorded in the tagged commit; never notes from a newer revision."""
    candidates = notes_candidates(tag)
    for path in candidates:
        data = git_text(tag + '^{commit}', path)
        if data is not None:
            return path, data
    raise ValueError('The tagged commit has no release notes: ' + ', '.join(candidates))


def next_notes():
    """Write the template for the next build; never commits, pushes or changes history."""
    version = product_version()
    build = int((ROOT / 'BUILD').read_text(encoding='ascii').strip()) + 1
    path = next_notes_path()
    if path.is_file():
        text = path.read_bytes().decode('utf-8', 'replace')
        if NOTES_PLACEHOLDER not in text and 'TODO' not in text:
            raise ValueError('docs/releases/next-build.md already holds release notes; keep them')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(next_notes_template(version, build), encoding='utf-8', newline='\n')
    print('Prepared', path, 'for build', build)


def prepare():
    if os.getenv('GITHUB_REF') != 'refs/heads/main':
        raise ValueError('Prepare a new release only from main')
    version = product_version()
    number = int((ROOT / 'BUILD').read_text(encoding='ascii').strip()) + 1
    tag = validate_ref(f'refs/tags/v{version}-build.{build_label(number)}', version, number)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    main = subprocess.check_output(['git', 'rev-parse', 'origin/main'], cwd=ROOT, text=True).strip()
    if head != main:
        raise ValueError('main changed; restart preparation at the current main revision')
    exists = subprocess.run(['git', 'show-ref', '--verify', '--quiet', 'refs/tags/' + tag], cwd=ROOT, check=False)
    if exists.returncode == 0:
        raise ValueError('Build tag already exists; retry its workflow without incrementing BUILD')
    if exists.returncode != 1:
        raise RuntimeError('Cannot inspect existing release tags')
    text = prepared_notes(version, number)
    snapshot = ROOT / NOTES_DIRECTORY / build_notes_name(version, number)
    if snapshot.exists():
        raise ValueError('Release notes for this build already exist; prepare the next build instead')
    number = bump_build(ROOT / 'BUILD')
    snapshot.write_bytes(text.encode('utf-8'))  # The tagged commit keeps the exact prepared notes.
    next_notes_path().unlink()  # The prepared notes belong to this build only.
    for args in [['config', 'user.name', 'github-actions[bot]'],
                 ['config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'],
                 ['add', '-A', '--', 'BUILD', NOTES_DIRECTORY],
                 ['commit', '-m', f'Prepare {tag}, build {number}'],
                 ['tag', '-a', tag, '-m', f'Video Descriptor {version}, build {number}'],
                 ['push', '--atomic', 'origin', 'HEAD:main', 'refs/tags/' + tag]]:
        subprocess.run(['git', *args], cwd=ROOT, check=True)
    gh('workflow', 'run', 'windows-release.yml', '--ref', tag)


def prepared_notes(version, number):
    """Release notes prepared for the next build; they must be meaningful and new."""
    path = next_notes_path()
    if not path.is_file():
        raise ValueError('Write docs/releases/next-build.md before preparing a release')
    data = path.read_bytes()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as error:
        raise ValueError('docs/releases/next-build.md must be UTF-8 text') from error
    problems = notes_problems(text)
    if problems:
        raise ValueError('docs/releases/next-build.md is not ready: ' + '; '.join(problems))
    previous = ROOT / NOTES_DIRECTORY / build_notes_name(version, number - 1)
    if previous.is_file() and previous.read_bytes() == data:
        raise ValueError('docs/releases/next-build.md repeats the previous build; write new release notes')
    return text


def validate_ref(ref, version, build=None):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Select an existing matching version/build tag')
    legacy = 'v' + version
    match = re.fullmatch(re.escape('refs/tags/' + legacy) + r'-build\.(\d+)', ref)
    if ref == 'refs/tags/' + legacy:
        return legacy  # Existing immutable version tags remain valid for retries.
    if match and build is not None and int(match[1]) == build and (match[1] == str(build) or match[1] == build_label(build)):
        return ref.removeprefix('refs/tags/')
    raise ValueError('Select an existing tag matching the product version and BUILD')


def artifact_names(version, build=None):
    prefix = f'VideoDescriptor-{version}' + (f'-build.{build}' if build is not None else '') + '-windows-x64'
    return [prefix + '-setup.exe', prefix + '.zip', 'SHA256SUMS.json', 'acceptance-provenance.json']


def validate():
    version = product_version()
    number = int((ROOT / 'BUILD').read_text(encoding='ascii').strip())
    tag = validate_ref(os.getenv('GITHUB_REF', ''), version, number)
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    tagged = subprocess.check_output(['git', 'rev-parse', 'refs/tags/' + tag + '^{commit}'], cwd=ROOT, text=True).strip()
    if tagged != sha:
        raise ValueError('Checked-out revision differs from the release tag')
    subprocess.run(['git', 'merge-base', '--is-ancestor', sha, 'origin/main'], cwd=ROOT, check=True)
    number = int((ROOT / 'BUILD').read_text(encoding='ascii').strip())
    previous = []
    tags = subprocess.check_output(['git', 'tag', '--merged', 'HEAD', '--list', 'v*'], cwd=ROOT, text=True).splitlines()
    for older in tags:
        if older == tag or not re.fullmatch(r'v\d+\.\d+\.\d+(?:-build\.\d+)?', older):
            continue
        try:
            value = subprocess.check_output(['git', 'show', older + ':BUILD'], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
            previous.append(int(value.strip()))
        except subprocess.CalledProcessError:
            continue  # Older versions predate the tracked BUILD file.
    if number < 1 or (previous and number <= max(previous)):
        raise ValueError('Increment BUILD before tagging a new release; retries must use the same tag')
    path, data = release_notes(tag)
    problems = notes_problems(data.decode('utf-8', 'replace'))
    if problems:
        raise ValueError(f'Release notes in {path} are not usable: ' + '; '.join(problems))
    return tag, version, sha


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def gh(*args):
    return subprocess.run(['gh', *map(str, args)], cwd=ROOT, check=True)


def publish(directory, tag, version, sha):
    number = int((ROOT / 'BUILD').read_text(encoding='ascii').strip())
    qualified = '-build.' in tag
    subprocess.run([sys.executable, str(ROOT / 'scripts/ci_artifacts.py'), '--directory', str(directory),
                    *(['--build-qualified'] if qualified else [])],
                   cwd=ROOT, check=True)
    names = artifact_names(version, tag.rsplit('-build.', 1)[1] if qualified else None)
    paths = {name: directory / name for name in names}
    for path in paths.values():
        if not path.is_file() or path.stat().st_size >= 2**31:
            raise ValueError('Missing release file or asset exceeds GitHub limit: ' + path.name)
    source, notes = release_notes(tag)
    text = notes.decode('utf-8')
    with tempfile.TemporaryDirectory(prefix='vd-release-notes-') as temporary:
        notes_file = Path(temporary) / 'release-notes.md'
        notes_file.write_bytes(notes)  # Publish exactly the notes recorded in the tagged commit.
        current = subprocess.run(['gh', 'release', 'view', tag, '--json', 'isDraft,assets,body'], cwd=ROOT,
                                 capture_output=True, text=True, check=False)
        if current.returncode:
            if 'release not found' not in current.stderr.lower():
                raise RuntimeError('Cannot inspect GitHub release; publication stopped')
            gh('release', 'create', tag, '--verify-tag', '--target', sha, '--draft',
               '--title', f'Video Descriptor {version} (build {tag.rsplit("-build.", 1)[1] if qualified else number})', '--notes-file', str(notes_file))
            state = {'isDraft': True, 'assets': [], 'body': text}
        else:
            state = json.loads(current.stdout)
            if (state.get('body') or '').strip() != text.strip():
                raise ValueError(f'Existing release notes differ from {source}; refusing to change them')
        existing = {item['name'] for item in state['assets']}
        if existing - set(names):
            raise ValueError('Existing release contains unexpected assets; nothing will be overwritten')
        missing = set(names) - existing
        if missing and not state['isDraft']:
            raise ValueError('Published release is incomplete; refusing to modify published assets')
        if missing:
            gh('release', 'upload', tag, *(paths[name] for name in names if name in missing))
        # Verify what users will download, including metadata, before exposing a draft.
        with tempfile.TemporaryDirectory(prefix='vd-release-download-') as download:
            command = ['release', 'download', tag, '--dir', download]
            for name in names:
                command.extend(['--pattern', name])
            gh(*command)
            for name, path in paths.items():
                if digest(Path(download) / name) != digest(path):
                    raise ValueError('GitHub asset differs from accepted bytes: ' + name)
        if state['isDraft']:
            gh('release', 'edit', tag, '--notes-file', str(notes_file), '--draft=false', '--latest')
    print('Verified Windows release:', tag, sha)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'validate', 'publish', 'next-notes'])
    parser.add_argument('--directory', type=Path, default=Path('accepted-windows'))
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
        return
    if args.action == 'next-notes':
        next_notes()
        return
    tag, version, sha = validate()
    if args.action == 'publish':
        publish(args.directory.resolve(), tag, version, sha)


if __name__ == '__main__':
    main()
