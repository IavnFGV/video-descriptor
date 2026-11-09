"""Run source code against local records; never build or install packages."""

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from local_build import build_lock, git


def health(url):
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url + '/health', timeout=1) as response:
            return json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return None


def assert_owned(info, config, previous):
    if (info.get('app') != 'video-descriptor-windows' or not info.get('development')
            or Path(info.get('workspace', '')).resolve() != Path(config['records_directory']).resolve()
            or not previous or info.get('instance') != previous.get('instance')
            or info.get('installation') != previous.get('installation')):
        raise ValueError('Порт занят другим экземпляром. Рабочее приложение не остановлено.')


def run(repo, command='start', open_browser=False):
    state = Path(git(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir')) / 'local-dev'
    config_path = state / 'config.json'
    if not config_path.is_file():
        raise ValueError('Сначала настройте .git/local-dev/config.json: python, port, development=true, records_directory.')
    config = json.loads(config_path.read_text(encoding='utf-8'))
    if config.get('development') is not True or type(config.get('port')) is not int or not 1024 <= config['port'] <= 65535:
        raise ValueError('Некорректная конфигурация локального запуска')
    workspace = Path(config['records_directory']).resolve()
    if not (workspace / 'output').is_dir() or not (workspace / 'data').is_dir():
        raise ValueError('Выберите существующую папку записей с data и output')
    python = Path(config['python'])
    if not python.is_file():
        raise ValueError('Не найден dev Python; зависимости автоматически не устанавливаются')
    url = f'http://127.0.0.1:{config["port"]}'
    status_path = state / 'status.json'
    previous = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
    info = health(url)
    if info:
        assert_owned(info, config, previous)
        if command in {'restart', 'stop'}:
            request = urllib.request.Request(url + '/api/native/stop', data=b'', method='POST',
                                             headers={'X-App-Instance': info['instance']})
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5):
                    pass
            except urllib.error.HTTPError as exc:
                detail = json.load(exc).get('error', str(exc))
                raise ValueError('Локальный запуск не перезапущен: ' + detail) from exc
            for _ in range(40):
                if not health(url):
                    break
                time.sleep(.2)
            else:
                raise ValueError('Локальный экземпляр ещё останавливается')
            info = None
    if command == 'stop':
        status_path.write_text(json.dumps({**previous, 'state': 'stopped'}, indent=2), encoding='utf-8')
        return {'state': 'stopped'}
    if info is None:
        commit = git(repo, 'rev-parse', 'HEAD')
        environment = {**os.environ, 'VIDEO_DESCRIPTOR_CONFIG': str(config_path),
                       'VIDEO_DESCRIPTOR_DEV_COMMIT': commit, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
        with (state / 'stdout.log').open('w', encoding='utf-8') as stdout, (state / 'stderr.log').open('w', encoding='utf-8') as stderr:
            process = subprocess.Popen([str(python), '-X', 'utf8', '-u', str(repo / 'windows-app/app.py'), '--no-browser'],
                                       cwd=repo, env=environment, stdout=stdout, stderr=stderr,
                                       stdin=subprocess.DEVNULL, creationflags=0x08000000 if os.name == 'nt' else 0)
        for _ in range(80):
            info = health(url)
            if info:
                if (info.get('development') is not True or info.get('source_commit') != commit
                        or Path(info.get('workspace', '')).resolve() != workspace):
                    raise ValueError('Порт ответил другим экземпляром; см. .git/local-dev/stderr.log')
                break
            if process.poll() is not None:
                raise ValueError('Локальное приложение завершилось; см. .git/local-dev/stderr.log')
            time.sleep(.2)
        else:
            raise ValueError('Локальное приложение не ответило; см. .git/local-dev/stderr.log')
        previous = {'pid': process.pid, 'source': str(repo)}
    result = {**previous, 'state': 'ready', 'url': url, 'instance': info['instance'],
              'installation': info['installation'], 'version': info['version'], 'commit': info['source_commit'],
              'workspace': str(workspace)}
    result.pop('error', None)
    status_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if open_browser:
        entry = config.get('entry_path', '/')
        if not entry.startswith('/') or entry.startswith('//'):
            raise ValueError('entry_path должен быть локальным маршрутом приложения')
        webbrowser.open(url + entry)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--command', choices=['start', 'restart', 'stop'], default='start')
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    state = Path(git(args.repo, 'rev-parse', '--path-format=absolute', '--git-common-dir')) / 'local-dev'
    try:
        with build_lock(state) as acquired:
            if not acquired:
                raise SystemExit('Локальный запуск уже обновляется другим процессом')
            result = run(args.repo.resolve(), args.command, args.open)
        print('Локальный запуск: ' + result['state'] + ' · ' + result.get('url', ''))
        if result['state'] == 'ready':
            print('Версия ' + result['version'] + ' · ' + result['commit'][:12])
    except (OSError, ValueError, KeyError) as exc:
        status_path = state / 'status.json'
        previous = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
        status_path.write_text(json.dumps({**previous, 'state': 'error', 'error': str(exc)},
                                          ensure_ascii=False, indent=2), encoding='utf-8')
        raise SystemExit(str(exc)) from exc


if __name__ == '__main__':
    main()
