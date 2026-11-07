"""Local Windows build queue. Builds committed sources; never installs the product."""
import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True, encoding='utf-8').strip()


def state_dir(repo):
    return Path(git(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir')) / 'local-build'


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for attempt in range(20):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 19:
                temporary.unlink(missing_ok=True)
                raise
            time.sleep(.05)


@contextlib.contextmanager
def build_lock(state):
    """OS-held lock: automatically released on exit/crash; shared with cleanup."""
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'build.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def now():
    return dt.datetime.now(dt.UTC).isoformat()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def reusable(record):
    if record.get('state') != 'ready':
        return False
    return bool(record.get('artifacts')) and all(
        Path(item['path']).is_file() and digest(Path(item['path'])) == item['sha256']
        for item in record['artifacts'])


def run_build(repo, state, config, sha):
    result_file = state / 'results' / (sha + '.json')
    if result_file.exists():
        previous = json.loads(result_file.read_text(encoding='utf-8'))
        if reusable(previous):
            write_json(state / 'status.json', previous)
            print('Already built:', previous['output'], flush=True)
            return True
    stamp = dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%S%fZ')
    run = Path(config['output']) / (sha[:12] + '-' + stamp)
    source, output = run / 'source', run / 'artifacts'
    run.mkdir(parents=True)
    output.mkdir()
    status = {'state': 'running', 'commit': sha, 'started': now(), 'output': str(output),
              'log': str(run / 'build.log'), 'stage': 'checkout'}
    env = {k: v for k, v in os.environ.items() if k not in {'PYTHONHOME', 'PYTHONPATH'}}
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    with (run / 'build.log').open('w', encoding='utf-8') as log:
        def step(name, command, cwd=source):
            status['stage'] = name
            write_json(state / 'status.json', status)
            log.write(f'\n[{now()}] {name}\n')
            log.flush()
            print(name, flush=True)
            subprocess.run([str(arg) for arg in command], cwd=cwd, env=env, stdout=log,
                           stderr=subprocess.STDOUT, check=True,
                           creationflags=0x08000000 if os.name == 'nt' else 0)
        try:
            step('checkout', ['git', 'worktree', 'add', '--detach', source, sha], repo)
            # Reuse verified small build tools; no user config, runtime workspace or models.
            tools = repo / 'windows-app/runtime/ci-tools'
            if tools.is_dir():
                shutil.copytree(tools, source / 'windows-app/runtime/ci-tools')
            sdk = Path(config['desktop_sdk'])
            metadata = sdk / 'desktop-build.json'
            inputs = json.loads((source / 'windows-app/release-inputs.json').read_text(encoding='utf-8'))
            if (metadata.exists() and json.loads(metadata.read_text()) == {
                    'source_sha256': digest(source / 'windows-app/DesktopHost.cs'),
                    'sdk_sha256': inputs['webview2']['sha256']}):
                shutil.copytree(sdk, source / 'windows-app/runtime/desktop-sdk')
            else:
                cached = Path(config['cache']) / 'webview2.nupkg'
                if cached.exists():
                    destination = source / 'windows-app/runtime/build-cache/webview2.nupkg'
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(cached, destination)
                step('desktop-sdk', ['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
                                     source / 'windows-app/Prepare-Desktop.ps1'])
            python = config['python']
            step('checks', [python, 'scripts/check-fast.py'])
            step('build', [python, 'windows-app/build_release.py', '--cache', config['cache'],
                           '--output', output, '--iscc', config['iscc']])
            version = inputs['version']
            archive = output / f'VideoDescriptor-{version}-windows-x64.zip'
            installer = output / f'VideoDescriptor-{version}-windows-x64-setup.exe'
            if not installer.is_file():
                raise ValueError('Installer was not produced')
            step('portable-smoke', [python, 'windows-app/verify_release.py', archive,
                                    '--output', output / 'verification-release.json'])
            status.update(state='ready', stage='done', version=version, finished=now(), artifacts=[
                {'path': str(path), 'sha256': digest(path), 'bytes': path.stat().st_size}
                for path in (archive, installer)])
            status['limits'] = ['No automatic installation or publication',
                                'Portable smoke only; no clean VM installer lifecycle or hardware inference']
            write_json(output / 'provenance.json', status)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            status.update(state='failed', finished=now(), error=str(error))
            log.write(f'\nFAILED: {error}\n')
        write_json(result_file, status)
        write_json(state / 'status.json', status)
    print(json.dumps(status, ensure_ascii=False), flush=True)
    return status['state'] == 'ready'


def drain(repo, state, config):
    success = True
    announced_wait = False
    while True:
        with build_lock(state) as acquired:
            if not acquired and not announced_wait:
                print('Build already running; request remains queued.', flush=True)
                announced_wait = True
            while acquired and (pending := sorted((state / 'queue').glob('*.json'), key=lambda p: p.stat().st_mtime_ns)):
                request = pending[0]
                sha = json.loads(request.read_text(encoding='utf-8'))['commit']
                if not re.fullmatch(r'[0-9a-f]{40,64}', sha):
                    raise ValueError('Invalid queued commit')
                success = run_build(repo, state, config, sha) and success
                request.unlink(missing_ok=True)
        if not acquired:
            time.sleep(1)
            continue
        # Check after releasing the lock: an enqueue racing with worker shutdown is
        # either picked up here or owns the now-free lock itself.
        if not list((state / 'queue').glob('*.json')):
            return success


def install_hook(repo):
    hooks = Path(git(repo, 'rev-parse', '--path-format=absolute', '--git-path', 'hooks'))
    hook = hooks / 'post-merge'
    marker = '# video-descriptor-local-build'
    if hook.exists() and marker not in hook.read_text(encoding='utf-8'):
        raise ValueError('Existing post-merge hook preserved; chain Build-Local.ps1 manually')
    hooks.mkdir(parents=True, exist_ok=True)
    hook.write_text('''#!/bin/sh
# video-descriptor-local-build
[ "$(git symbolic-ref --quiet --short HEAD)" = "main" ] || exit 0
root=$(git rev-parse --show-toplevel) || exit 0
unset $(git rev-parse --local-env-vars)
if [ -f "$root/scripts/Build-Local.ps1" ]; then
  powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$root/scripts/Build-Local.ps1" -Background
fi
exit 0
''', encoding='utf-8', newline='\n')
    hook.chmod(0o755)
    return hook


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['configure', 'build', 'status', 'install-hook'])
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--ref', default='HEAD')
    for name in ('python', 'cache', 'iscc', 'desktop-sdk', 'output'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    repo = Path(git(args.repo, 'rev-parse', '--show-toplevel')).resolve()
    state = state_dir(repo)
    config_file = state / 'config.json'
    if args.command == 'configure':
        settings = {key: str(getattr(args, key).resolve()) for key in ('python', 'cache', 'iscc')
                    if getattr(args, key)}
        if len(settings) != 3:
            parser.error('configure requires --python, --cache and --iscc')
        if not Path(settings['python']).is_file() or not Path(settings['iscc']).is_file():
            parser.error('Python and ISCC must already be installed')
        settings['desktop_sdk'] = str((args.desktop_sdk or repo / 'windows-app/runtime/desktop-sdk').resolve())
        settings['output'] = str((args.output or repo / 'dist/local').resolve())
        write_json(config_file, settings)
        print(config_file)
        return 0
    if args.command == 'install-hook':
        print(install_hook(repo))
        return 0
    if args.command == 'status':
        status_file = state / 'status.json'
        print(status_file.read_text(encoding='utf-8') if status_file.exists() else 'No local builds yet.')
        print('Queued:', len(list((state / 'queue').glob('*.json'))))
        return 0
    config = json.loads(config_file.read_text(encoding='utf-8'))
    sha = git(repo, 'rev-parse', '--verify', '--end-of-options', args.ref + '^{commit}')
    write_json(state / 'queue' / (sha + '.json'), {'commit': sha, 'requested': now()})
    return 0 if drain(repo, state, config) else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print('Local build error:', error, file=sys.stderr)
        sys.exit(1)
