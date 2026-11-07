"""Local Windows build queue. Builds committed sources; never installs the product."""
import argparse
import contextlib
import datetime as dt
import hashlib
import html
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
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def atomic_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(content, encoding='utf-8')
    for attempt in range(20):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 19:
                temporary.unlink(missing_ok=True)
                raise
            time.sleep(.05)


def update_status(state, config, record):
    """A fixed, self-refreshing local page; no server or external resources."""
    write_json(state / 'status.json', record)
    if record['state'] == 'ready':
        write_json(state / 'last-success.json', record)
    previous_file = state / 'last-success.json'
    ready = record if record['state'] == 'ready' else (
        json.loads(previous_file.read_text(encoding='utf-8')) if previous_file.exists() else None)
    labels = {'checkout': 'Подготавливаем исходники', 'desktop-sdk': 'Подготавливаем desktop SDK',
              'checks': 'Выполняем локальные проверки', 'build': 'Собираем ZIP и установщик',
              'portable-smoke': 'Проверяем запуск пакета', 'done': 'Готово'}
    heading = {'running': 'Сборка выполняется', 'ready': 'Сборка готова', 'failed': 'Ошибка сборки'}[record['state']]

    def link(path, title):
        return f'<a class="vd-link" href="{html.escape(Path(path).resolve().as_uri(), quote=True)}">{html.escape(title)}</a>'

    downloads = ''
    if ready:
        downloads = '<section><h2>Последняя готовая версия: ' + html.escape(ready.get('version', '')) + '</h2><p>' + ' · '.join(
            link(item['path'], 'Установщик' if item['path'].endswith('.exe') else 'ZIP')
            for item in ready.get('artifacts', [])) + '</p></section>'
    root = Path(__file__).resolve().parents[1]
    styles = '\n'.join((root / 'design-system' / name).read_text(encoding='utf-8')
                       for name in ('tokens.css', 'components.css'))
    error = '<p class="vd-error" role="alert">' + html.escape(record.get('error', '')) + '</p>' if record['state'] == 'failed' else ''
    log = link(record['log'], 'Открыть журнал сборки') if record.get('log') else ''
    page = f'''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="3">
<title>Video Descriptor — локальная сборка</title><style>{styles}
body{{font:var(--vd-body)/1.5 var(--vd-font);color:var(--vd-text);background:var(--vd-canvas);margin:var(--vd-space-6)}}
main{{max-width:var(--vd-reading-width);margin:auto;background:var(--vd-surface);padding:var(--vd-space-6);border:1px solid var(--vd-border);border-radius:var(--vd-radius-card)}}
p,section{{overflow-wrap:anywhere}}section{{margin-top:var(--vd-space-6)}}</style><main>
<h1>Локальная сборка</h1><h2>{heading}</h2><p>{html.escape(labels.get(record.get('stage'), record.get('stage', '')))}</p>
{error}<p>{log}</p>{downloads}<details><summary>Технические сведения</summary>
<p>Коммит: {html.escape(record.get('commit', ''))}</p><p>Начало (UTC): {html.escape(record.get('started', ''))}</p>
</details><p>Страница обновляется автоматически каждые 3 секунды. Сборка не устанавливает приложение.</p></main></html>'''
    atomic_text(Path(config['output']) / 'build-status.html', page)


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


def publish_ready(record, base):
    """Public downloads use version folders; technical runs remain in Git-local state."""
    if not re.fullmatch(r'\d+\.\d+\.\d+', record['version']):
        raise ValueError('Invalid release version')
    destination = Path(base) / record['version']
    destination.mkdir(parents=True, exist_ok=True)
    original = Path(record['output'])
    for source in original.iterdir():
        if not source.is_file() or source.name == 'provenance.json':
            continue
        if source.suffix not in {'.zip', '.exe', '.json'}:
            continue
        target = destination / source.name
        if source.resolve() != target.resolve():
            temporary = target.with_name(target.name + '.publishing')
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
    record['output'] = str(destination)
    for artifact in record['artifacts']:
        artifact['path'] = str(destination / Path(artifact['path']).name)
    write_json(destination / 'provenance.json', record)
    return record


def run_build(repo, state, config, sha):
    result_file = state / 'results' / (sha + '.json')
    if result_file.exists():
        previous = json.loads(result_file.read_text(encoding='utf-8'))
        if reusable(previous):
            previous = publish_ready(previous, config['output'])
            write_json(result_file, previous)
            update_status(state, config, previous)
            print('Already built:', previous['output'], flush=True)
            return True
    stamp = dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%S%fZ')
    run = state / 'runs' / (sha[:12] + '-' + stamp)
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
            update_status(state, config, status)
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
            status = publish_ready(status, config['output'])
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            status.update(state='failed', finished=now(), error=str(error))
            log.write(f'\nFAILED: {error}\n')
        write_json(result_file, status)
        update_status(state, config, status)
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
