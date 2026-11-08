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
import stat
import subprocess
import sys
import threading
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


def update_status(state, config, record, *, render_only=False):
    """A fixed, self-refreshing local page; no server or external resources."""
    if not render_only:
        write_json(state / 'status.json', record)
    if record['state'] == 'ready' and not render_only:
        write_json(state / 'last-success.json', record)
    previous_file = state / 'last-success.json'
    ready = record if record['state'] == 'ready' else (
        json.loads(previous_file.read_text(encoding='utf-8')) if previous_file.exists() else None)
    labels = {'checkout': 'Подготавливаем исходники', 'desktop-sdk': 'Подготавливаем desktop SDK',
              'checks': 'Выполняем локальные проверки', 'build': 'Собираем ZIP и установщик',
              'cached-build': 'Собираем полный установщик из кеша компонентов',
              'cached-smoke': 'Проверяем установку и обновление полного пакета',
              'portable-smoke': 'Проверяем запуск пакета', 'domestic-smoke': 'Проверяем встроенные модели', 'done': 'Готово'}
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
    detail = status_details(state, record)
    elapsed = duration(record.get('started'), record.get('finished'))
    stage_elapsed = duration(record.get('stage_started') or detail['stage_started'], record.get('finished'))
    details_html = f'<p><strong>{html.escape(detail["step"])}</strong></p>'
    details_html += f'<p>Всего: {elapsed} · На этапе: {stage_elapsed}</p>'
    details_html += '<p>Коммит: <code>' + html.escape(record.get('commit', '')[:12]) + '</code> · Профиль: ' + ({'domestic':'Полный · без кеша', 'cached':'Полный · кеш компонентов'}.get(record.get('profile'), 'Стандартный')) + '</p>'
    details_html += '<section><h2>Очередь: ' + str(len(detail['queue'])) + '</h2>'
    details_html += ('<ol>' + ''.join('<li><code>' + html.escape(item['commit'][:12]) + '</code> · ' + ('Полный · кеш компонентов' if item.get('cached') else 'Полный · без кеша' if item.get('domestic') else 'Стандартный') + '</li>' for item in detail['queue']) + '</ol>') if detail['queue'] else '<p>Ожидающих сборок нет.</p>'
    details_html += '</section><section><h2>Последние сообщения — новые сверху</h2><p>' + html.escape(detail['activity']) + '</p><pre>' + html.escape('\n'.join(reversed(detail['tail'].splitlines())) if detail['tail'] else 'Журнал пока пуст.') + '</pre></section>'
    page = f'''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="3">
<title>Video Descriptor — локальная сборка</title><style>{styles}
body{{font:var(--vd-body)/1.5 var(--vd-font);color:var(--vd-text);background:var(--vd-canvas);margin:var(--vd-space-6)}}
main{{max-width:var(--vd-reading-width);margin:auto;background:var(--vd-surface);padding:var(--vd-space-6);border:1px solid var(--vd-border);border-radius:var(--vd-radius-card)}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:var(--vd-caption);max-height:24em;overflow:auto;background:var(--vd-subtle);padding:var(--vd-space-4)}}p,section{{overflow-wrap:anywhere}}section{{margin-top:var(--vd-space-6)}}</style><main>
<h1>Локальная сборка {html.escape(record.get("version", ""))}</h1><h2>{heading}</h2><p>{html.escape(labels.get(record.get('stage'), record.get('stage', '')))}</p>
{details_html}{error}<p>{log}</p>{downloads}<details><summary>Технические сведения</summary>
<p>Коммит: {html.escape(record.get('commit', ''))}</p><p>Начало (UTC): {html.escape(record.get('started', ''))}</p>
</details><p>Страница обновляется автоматически каждые 3 секунды. Сборка не устанавливает приложение.</p></main></html>'''
    atomic_text(Path(config.get('status_output', config['output'])) / 'build-status.html', page)


def duration(start, end=None):
    if not start:
        return '—'
    seconds = max(0, int(((dt.datetime.fromisoformat(end) if end else dt.datetime.now(dt.UTC)) - dt.datetime.fromisoformat(start)).total_seconds()))
    return f'{seconds // 60} мин {seconds % 60:02d} с'


def status_details(state, record):
    tail, modified = '', None
    if record.get('log'):
        path = Path(record['log'])
        try:
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 12000))
                tail = '\n'.join(stream.read().decode('utf-8', errors='replace').splitlines()[-24:])
            modified = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC).isoformat()
        except FileNotFoundError:
            pass
    step = {'checkout': 'Создание отдельной копии исходников', 'checks': 'Проверка кода и тесты',
            'desktop-sdk': 'Подготовка оболочки Windows', 'build': 'Подготовка файлов приложения',
            'portable-smoke': 'Проверка запуска готового ZIP', 'domestic-smoke': 'Проверка моделей в пакете',
            'done': 'Готовый пакет опубликован локально', 'cached-build': 'Переиспользуем готовый архив Python, библиотек и моделей',
            'cached-smoke': 'Проверяем полный установщик и сохранность данных при обновлении'}.get(record.get('stage'), 'Ожидаем сведения об этапе')
    if record.get('stage') == 'cached-build' and 'CACHE MISS' in tail:
        step = 'Первый прогрев кеша: проверяем и сжимаем компоненты один раз'
    if record.get('stage') == 'build':
        if any(marker in tail for marker in ('ZIP:', 'Preprocessing', 'Building Windows installer',
                                               'Parsing [', 'Creating setup files', 'Compressing:',
                                               'Creating Setup', 'Compile successful')):
            step = 'ZIP создан. Работает компилятор Windows-установщика (Inno Setup)'
        elif 'Writing reproducible ZIP' in tail:
            step = 'Создание ZIP-архива с приложением и моделями'
        elif 'Recording payload manifest' in tail:
            step = 'Проверка состава пакета и запись контрольных сумм'
    queue = []
    for path in sorted((state / 'queue').glob('*.json'), key=lambda item: item.stat().st_mtime_ns):
        try:
            item = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            continue
        active = record.get('state') == 'running' and item.get('commit') == record.get('commit') and ('cached' if item.get('cached') else 'domestic' if item.get('domestic') else 'standard') == record.get('profile', 'standard')
        if not active:
            queue.append(item)
    activity = ('Последняя запись в журнале: ' + duration(modified) + ' назад. ' if modified else '')
    activity += 'Процент готовности этого этапа не сообщается. Пауза в журнале сама по себе не означает зависание.' if record.get('state') == 'running' else 'Сборка завершена.'
    starts = re.findall(r'^\[([^\]]+)\] ' + re.escape(record.get('stage', '')) + r'$', tail, re.MULTILINE)
    return {'tail': tail, 'step': step, 'queue': queue, 'activity': activity,
            'stage_started': starts[-1] if starts else None}


def watch_status(state, config):
    """Refresh the existing dashboard without changing worker state or its queue."""
    while True:
        path = state / 'status.json'
        if not path.exists():
            return
        record = json.loads(path.read_text(encoding='utf-8'))
        update_status(state, config, record, render_only=True)
        if record.get('state') != 'running' and not list((state / 'queue').glob('*.json')):
            return
        time.sleep(3)


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


def build_environment(config, run_name):
    """Keep build/verification scratch files on the configured build-data volume."""
    scratch = Path(config.get('temp_root', str(Path(config['cache']) / 'temp'))) / run_name
    scratch.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if key not in {'PYTHONHOME', 'PYTHONPATH'}}
    env.update(TEMP=str(scratch.resolve()), TMP=str(scratch.resolve()), TMPDIR=str(scratch.resolve()),
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    return env


def remove_tree(path, boundary):
    """Delete an owned scratch tree, clearing only disposable read-only attributes."""
    path, boundary = Path(path), Path(boundary).resolve()
    target = path.resolve()
    if target == boundary or not target.is_relative_to(boundary):
        raise ValueError('Cleanup target escaped its boundary')
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise ValueError('Linked cleanup root refused')

    def retry_readonly(function, name, error):
        candidate = Path(name)
        if not isinstance(error, PermissionError) or not candidate.resolve().is_relative_to(target):
            raise error
        mode = candidate.stat().st_mode | stat.S_IREAD | stat.S_IWRITE
        candidate.chmod(mode | stat.S_IEXEC if candidate.is_dir() else mode)
        function(name)

    shutil.rmtree(path, onexc=retry_readonly)


def cleanup_run(repo, source, scratch, run):
    """Remove only the two scratch roots created by this build, after children exit."""
    failures = []
    for target, boundary in ((source, run), (scratch, scratch.parent)):
        if not target.exists():
            continue
        try:
            resolved = target.resolve()
            if resolved == boundary.resolve() or not resolved.is_relative_to(boundary.resolve()):
                raise ValueError('Cleanup boundary mismatch: ' + str(target))
            if target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()):
                raise ValueError('Linked scratch root refused: ' + str(target))
            if target == source and (source / '.git').is_file():
                subprocess.run(['git', '-C', str(repo), 'worktree', 'remove', '--force', str(source)],
                               check=True, capture_output=True)
            else:
                remove_tree(target, boundary)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            failures.append(str(error))
    return failures


def run_build(repo, state, config, sha):
    domestic = config.get('domestic', False)
    cached = config.get('cached', False)
    if domestic or cached:
        config = {**config, 'status_output': config['output'], 'output': str(Path(config['output']) / ('cached' if cached else 'domestic'))}
    result_file = state / 'results' / (sha + ('-cached' if cached else '-domestic' if domestic else '') + '.json')
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
              'profile': 'cached' if cached else 'domestic' if domestic else 'standard',
              'log': str(run / 'build.log'), 'stage': 'checkout'}
    env = build_environment(config, run.name)
    status['temporary_directory'] = env['TEMP']
    with (run / 'build.log').open('w', encoding='utf-8') as log:
        def step(name, command, cwd=source):
            status['stage'] = name
            status['stage_started'] = now()
            update_status(state, config, status)
            log.write(f'\n[{now()}] {name}\n')
            log.flush()
            print(name, flush=True)
            stopped = threading.Event()

            def refresh():
                while not stopped.wait(3):
                    update_status(state, config, status, render_only=True)

            monitor = threading.Thread(target=refresh, daemon=True)
            monitor.start()
            try:
                subprocess.run([str(arg) for arg in command], cwd=cwd, env=env, stdout=log,
                               stderr=subprocess.STDOUT, check=True,
                               creationflags=0x08000000 if os.name == 'nt' else 0)
            finally:
                stopped.set()
                monitor.join()

        try:
            step('checkout', ['git', 'worktree', 'add', '--detach', source, sha], repo)
            # Reuse verified small build tools; no user config, runtime workspace or models.
            tools = repo / 'windows-app/runtime/ci-tools'
            if tools.is_dir():
                shutil.copytree(tools, source / 'windows-app/runtime/ci-tools')
            sdk = Path(config['desktop_sdk'])
            metadata = sdk / 'desktop-build.json'
            inputs = json.loads((source / 'windows-app/release-inputs.json').read_text(encoding='utf-8'))
            status['version'] = inputs['version']
            if (metadata.exists() and json.loads(metadata.read_text()) == {
                    'source_sha256': digest(source / 'windows-app/DesktopHost.cs'),
                    'sdk_sha256': inputs['webview2']['sha256']}):
                shutil.copytree(sdk, source / 'windows-app/runtime/desktop-sdk')
            else:
                sdk_archive = Path(config['cache']) / 'webview2.nupkg'
                if sdk_archive.exists():
                    destination = source / 'windows-app/runtime/build-cache/webview2.nupkg'
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(sdk_archive, destination)
                step('desktop-sdk', ['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
                                     source / 'windows-app/Prepare-Desktop.ps1'])
            python = config['python']
            step('checks', [python, 'scripts/check-fast.py'])
            if cached:
                seed = None
                seed_sha = None
                for result in sorted((state / 'results').glob('*-domestic.json'), key=lambda p: p.stat().st_mtime, reverse=True):
                    record = json.loads(result.read_text(encoding='utf-8'))
                    archives = [Path(item['path']) for item in record.get('artifacts', [])
                                if item['path'].endswith('.zip') and Path(item['path']).is_file()]
                    if record.get('state') == 'ready' and archives:
                        seed = archives[0]
                        seed_sha = next(item['sha256'] for item in record['artifacts'] if Path(item['path']) == seed)
                        break
                arguments = [python, 'windows-app/build_cached.py', '--cache', config['cache'],
                             '--output', output, '--iscc', config['iscc']]
                if seed:
                    arguments += ['--seed', seed, '--seed-sha', seed_sha]
                if config.get('domestic_inputs'):
                    arguments += ['--domestic-inputs', config['domestic_inputs']]
                step('cached-build', arguments)
                step('cached-smoke', [python, 'windows-app/verify_cached.py', '--output', output])
                installer = output / f'VideoDescriptor-{inputs["version"]}-windows-x64-setup.exe'
                status['component_cache_key'] = json.loads((output / 'cache-reference.json').read_text(encoding='utf-8'))['key']
                (output / 'app-payload.zip').unlink(missing_ok=True)
                (output / 'cache-reference.json').unlink(missing_ok=True)
                write_json(output / 'SHA256SUMS.json', [{'file': installer.name, 'sha256': digest(installer), 'bytes': installer.stat().st_size}])
                status.update(state='ready', stage='done', version=inputs['version'], finished=now(), artifacts=[
                    {'path': str(installer), 'sha256': digest(installer), 'bytes': installer.stat().st_size}])
                status['limits'] = ['Complete offline installer; cached runtime and host-scoped CPU validation',
                                    'Isolated fixture AppId lifecycle; not a clean VM or NPU/GPU acceptance']
            else:
                profile_args = []
                if domestic:
                    if not config.get('domestic_inputs'):
                        raise ValueError('Configure --domestic-inputs before requesting a domestic build')
                    profile_args = ['--domestic', '--domestic-inputs', config['domestic_inputs']]
                step('build', [python, 'windows-app/build_release.py', '--cache', config['cache'],
                               '--output', output, '--iscc', config['iscc'], *profile_args])
                version = inputs['version']
                archive = output / f'VideoDescriptor-{version}-windows-x64.zip'
                installer = output / f'VideoDescriptor-{version}-windows-x64-setup.exe'
                if not installer.is_file():
                    raise ValueError('Installer was not produced')
                step('portable-smoke', [python, 'windows-app/verify_release.py', archive,
                                        '--output', output / 'verification-release.json'])
                if domestic:
                    step('domestic-smoke', [python, 'windows-app/verify_domestic.py', archive,
                                           '--output', output / 'verification-domestic.json'])
                status.update(state='ready', stage='done', version=version, finished=now(), artifacts=[
                    {'path': str(path), 'sha256': digest(path), 'bytes': path.stat().st_size}
                    for path in (archive, installer)])
                status['limits'] = ['No automatic installation or publication',
                                    'Portable smoke only; no clean VM installer lifecycle or hardware inference']
            status = publish_ready(status, config['output'])
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            status.update(state='failed', finished=now(), error=str(error))
            log.write(f'\nFAILED: {error}\n')
        finally:
            failures = cleanup_run(repo, source, Path(env['TEMP']), run)
            # Published files live outside the run; partial/duplicate packages are disposable.
            if output.exists() and output.resolve().parent == run.resolve():
                try:
                    remove_tree(output, run)
                except OSError as error:
                    failures.append(str(error))
            if failures:
                status['cleanup_errors'] = failures
                log.write('\nCleanup warning: ' + '; '.join(failures) + '\n')
            else:
                status['temporary_files_removed'] = True
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
                queued = json.loads(request.read_text(encoding='utf-8'))
                sha = queued['commit']
                if not re.fullmatch(r'[0-9a-f]{40,64}', sha):
                    raise ValueError('Invalid queued commit')
                success = run_build(repo, state, {**config, 'domestic': queued.get('domestic', False), 'cached': queued.get('cached', False)}, sha) and success
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
    parser.add_argument('command', choices=['configure', 'build', 'status', 'watch-status', 'install-hook'])
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--ref', default='HEAD')
    profiles = parser.add_mutually_exclusive_group()
    profiles.add_argument('--domestic', action='store_true')
    profiles.add_argument('--cached', action='store_true')
    for name in ('python', 'cache', 'iscc', 'desktop-sdk', 'output', 'domestic-inputs', 'temp-root'):
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
        if args.temp_root:
            settings['temp_root'] = str(args.temp_root.resolve())
        if args.domestic_inputs:
            settings['domestic_inputs'] = str(args.domestic_inputs.resolve())
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
    if args.command == 'watch-status':
        watch_status(state, config)
        return 0
    sha = git(repo, 'rev-parse', '--verify', '--end-of-options', args.ref + '^{commit}')
    write_json(state / 'queue' / (sha + ('-cached' if args.cached else '-domestic' if args.domestic else '') + '.json'),
               {'commit': sha, 'requested': now(), 'domestic': args.domestic, 'cached': args.cached})
    success = drain(repo, state, config)
    # Once the queue is idle, purge known generated leftovers under the same OS lock.
    with build_lock(state) as acquired:
        if acquired:
            from clean_local import apply_plan, plan, refuse_active_builds
            try:
                refuse_active_builds()
                apply_plan(plan(repo, config))
                git(repo, 'worktree', 'prune')
            except (OSError, ValueError, RuntimeError) as error:
                print('Cleanup postponed:', error, file=sys.stderr)
    return 0 if success else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print('Local build error:', error, file=sys.stderr)
        sys.exit(1)
