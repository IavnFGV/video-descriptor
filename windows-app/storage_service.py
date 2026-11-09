"""Explicit, verified storage relocation; original data survives until cleanup."""
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import ExitStack
from pathlib import Path

from video_descriptor.action_history import record
from video_descriptor.jobs import read_json, write_json
from video_descriptor.platform_support import lock_file


def local_folder(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ValueError('Укажите полный путь к локальной папке')
    path = Path(value.strip())
    if not path.is_absolute() or str(path).startswith('\\\\') or '..' in path.parts:
        raise ValueError('Нужен полный путь к локальной папке')
    path = path.resolve()
    if path == Path(path.anchor) or path == Path.home():
        raise ValueError('Выберите отдельную папку, а не корень диска или профиль пользователя')
    return path


def overlaps(a, b):
    return a == b or a in b.parents or b in a.parents


def remap(value, source, target, key=''):
    if isinstance(value, dict):
        return {k: remap(v, source, target, k) for k, v in value.items()}
    if isinstance(value, list):
        return [remap(v, source, target, key) for v in value]
    path_key = key in {'workspace', 'root', 'folder', 'video', 'audio', 'model', 'path', 'runtime', 'output', 'source', 'python', 'command'} or key.endswith(('_path', '_directory', '_python'))
    if isinstance(value, str) and path_key:
        path = Path(value)
        if path.is_absolute() and path.is_relative_to(source):
            return str(target / path.relative_to(source))
    return value


def files(root):
    result = []
    if not root.exists():
        return result
    for path in root.rglob('*'):
        if path.is_symlink() or path.is_junction():
            raise ValueError('В папке найдена ссылка. Перенос отменён; исходные файлы сохранены.')
        if path.is_file() and path.suffix != '.lock' and path.name != '.storage-transfer.json':
            result.append(path)
    return result


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class StorageService:
    lease_timeout = 45

    def __init__(self, setup, components):
        self.setup, self.components = setup, components
        self.here, self.manager = setup.here, setup.manager
        self.path = self.here / 'runtime/storage-transfer.json'
        self.lock = threading.RLock()
        self.active = False
        self.switched = False
        self.state = read_json(self.path, {})
        if self.state.get('status') in {'copied', 'done', 'error'} and self.state.get('cleanup_pending'):
            current = self.components.root if self.state.get('kind') == 'components' else self.manager.value['workspace']
            if Path(current).resolve() == Path(self.state['target']).resolve():
                if self.state.get('kind') == 'components' and not self.state.get('records_rebased'):
                    if read_json(Path(self.state['target']) / '.storage-transfer.json', {}).get('token') != self.state.get('token'):
                        raise ValueError('Не подтверждена новая папка компонентов')
                    self.rewrite_json(Path(self.manager.value['workspace']), Path(self.state['source']), Path(self.state['target']))
                    self.state['records_rebased'] = True
                self.state.update(status='done', message='Новая папка используется. Можно очистить проверенные файлы старой копии.')
            else:
                self.state.update(status='error', cleanup_pending=False, message='Переключение не завершено. Исходная папка используется; копия сохранена в папке назначения.')
            self.save()
        if self.state.get('status') == 'running':
            self.state.update(status='error', message='Перенос прерван. Исходная папка сохранена; незавершённая копия находится в папке назначения.')
            self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.path, self.state)
        status = self.state.get('status')
        if status != getattr(self, '_logged_status', None):
            record('storage_state', stage='storage', status=status)
            self._logged_status = status

    def snapshot(self):
        with self.lock:
            return {'components': str(self.components.root.resolve()), 'records': self.manager.value['workspace'],
                    'active': self.active, 'restart_required': self.switched,
                    'transfer': {k: v for k, v in self.state.items() if k != 'files'}}

    def blocked(self):
        return self.active or self.switched

    def start(self, body):
        if body.get('confirmed') is not True:
            raise ValueError('Подтвердите перенос данных')
        kind = body.get('kind')
        if kind not in {'components', 'records'}:
            raise ValueError('Выберите папку моделей или записей')
        source = Path(self.components.root if kind == 'components' else self.manager.value['workspace']).resolve()
        other = Path(self.manager.value['workspace'] if kind == 'components' else self.components.root).resolve()
        target = local_folder(body.get('directory'))
        if overlaps(source, target) or overlaps(other, target) or overlaps(self.here, target):
            raise ValueError('Папки должны быть отдельными: без вложения друг в друга и вне папки кода приложения')
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ValueError('Выберите новую или пустую папку: существующие файлы не перезаписываются')
        with self.manager._lock, self.lock:
            self.setup.guard()
            if self.blocked() or self.state.get('cleanup_pending'):
                raise RuntimeError('Сначала завершите предыдущий перенос и очистку старой папки')
            if self.components.active or self.components.plan.get('state') == 'running':
                raise RuntimeError('Дождитесь завершения подготовки компонентов')
            self.active = True
            self.manager.operation = 'storage-transfer'
            self.state = {'status': 'running', 'kind': kind, 'source': str(source), 'target': str(target),
                          'token': uuid.uuid4().hex, 'message': 'Проверяем свободное место и копируем файлы', 'bytes': 0, 'total': 0}
            try:
                self.save()
            except OSError:
                self.active = False
                self.manager.operation = None
                raise
        threading.Thread(target=self.run, name='storage-transfer', daemon=True).start()
        return self.snapshot()

    def leases(self, stack, source, kind):
        names = ['operation.lock', 'preparation.lock'] if kind == 'components' else ['output/jobs/worker.lock', 'output/postprocess.lock']
        for name in names:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            stream = stack.enter_context(path.open('a+'))
            deadline = time.monotonic() + self.lease_timeout
            while True:
                try:
                    lock_file(stream)
                    break
                except (BlockingIOError, PermissionError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Папка ещё используется обработчиком. Завершите использующее её приложение и повторите перенос.') from None
                    self.state['message'] = 'Ожидаем освобождения папки после обработки записей'
                    time.sleep(.25)

    def run(self):
        source, target = Path(self.state['source']), Path(self.state['target'])
        try:
            with ExitStack() as stack:
                self.leases(stack, source, self.state['kind'])
                if self.state['kind'] == 'components':
                    self.components.close()  # Only the app-owned Ollama child, never the user's service.
                self.pause_owned_readers(source)
                entries = files(source)
                total = sum(p.stat().st_size for p in entries)
                target.mkdir(parents=True, exist_ok=True)
                if any(target.iterdir()):
                    raise ValueError('Папка назначения больше не пуста. Файлы не перезаписаны.')
                if shutil.disk_usage(target).free < total + 64 * 1024**2:
                    raise ValueError('Недостаточно места: нужна полная копия данных и ещё 64 МиБ')
                self.state['total'] = total

                def copy(path):
                    relative = path.relative_to(source)
                    dest = target / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    checksum = hashlib.sha256()
                    with path.open('rb') as inp, dest.open('xb') as out:
                        while chunk := inp.read(1024 * 1024):
                            out.write(chunk)
                            checksum.update(chunk)
                            with self.lock:
                                self.state['bytes'] += len(chunk)
                    value = checksum.hexdigest()
                    if digest(dest) != value:
                        raise ValueError('Не совпала контрольная сумма: ' + str(relative))
                    shutil.copystat(path, dest)
                    return {'path': relative.as_posix(), 'source_hash': value}

                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    copied = list(pool.map(copy, entries))
                with self.lock:
                    self.state.update(message='Файлы скопированы. Обновляем пути и проверяем окружения', files=copied)
                self.rewrite(target, source)
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    hashes = list(pool.map(digest, [target / item['path'] for item in copied]))
                for item, value in zip(copied, hashes, strict=True):
                    item['target_hash'] = value
                # Detect concurrent source changes before publishing any configuration.
                if {str(p.relative_to(source)) for p in files(source)} != {str(p.relative_to(source)) for p in entries}:
                    raise ValueError('Исходная папка изменилась во время переноса. Настройки не изменены.')
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    actual = list(pool.map(digest, entries))
                if actual != [i['source_hash'] for i in copied]:
                    raise ValueError('Исходные файлы изменились. Настройки не изменены.')
                config_path = self.here / 'config.local.json'
                saved = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
                if not isinstance(saved, dict):
                    raise TypeError('Настройки повреждены. Исходные данные сохранены.')
                updated = remap(saved, source, target)
                updated['ai_components_directory' if self.state['kind'] == 'components' else 'records_directory'] = str(target)
                # Save recovery journal before the atomic configuration switch.
                with self.lock:
                    self.state.update(status='copied', cleanup_pending=True)
                    self.save()
                marker = {'token': self.state['token'], 'source': str(source), 'target': str(target)}
                write_json(source / '.storage-transfer.json', marker)
                write_json(target / '.storage-transfer.json', marker)
                write_json(config_path, updated)
                with self.lock:
                    self.switched = True
                    self.state.update(status='done', message='Перенос проверен. Полностью завершите приложение через меню трея и откройте снова. Затем здесь можно очистить старую папку.')
                    self.save()
        except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
            with self.lock:
                self.state['cleanup_pending'] = self.switched
                self.state.update(status='error', message='Перенос не завершён: ' + str(exc) + '. Исходные данные сохранены.')
                self.save()
        finally:
            with self.manager._lock, self.lock:
                self.active = False
                self.manager.operation = None

    @staticmethod
    def rewrite_json(folder, source, target):
        for path in folder.rglob('*.json'):
            # Package metadata is immutable; only app state, recordings and config carry our paths.
            if 'site-packages' in path.parts:
                continue
            try:
                value = json.loads(path.read_text(encoding='utf-8'))
            except (UnicodeError, ValueError):
                continue
            changed = remap(value, source, target)
            if value != changed:
                write_json(path, changed)

    def rewrite(self, target, source):
        self.rewrite_json(target, source, target)
        for cfg in target.rglob('pyvenv.cfg'):
            text = cfg.read_text(encoding='utf-8')
            cfg.write_text(text.replace(str(source), str(target)), encoding='utf-8')
            python = cfg.parent / 'Scripts/python.exe'
            if python.is_file():
                # Recreate console-script launchers with their new absolute interpreter path, offline.
                script = "import sys,importlib.metadata as m; from pip._vendor.distlib.scripts import ScriptMaker; maker=ScriptMaker(None,sys.prefix+'/Scripts'); maker.clobber=True; maker.variants={''}; [maker.make(e.name+' = '+e.value) for e in m.entry_points(group='console_scripts')]; print(sys.prefix)"
                result = subprocess.run([str(python), '-X', 'utf8', '-c', script], check=False, capture_output=True,
                                        text=True, encoding='utf-8', timeout=120,
                                        creationflags=0x08000000 if os.name == 'nt' else 0)
                if result.returncode or Path(result.stdout.strip()).resolve() != cfg.parent.resolve():
                    raise ValueError('Не удалось проверить Python-окружение на новом месте')

    def pause_owned_readers(self, source):
        # Stop only a recorded child from this installation with the exact original command.
        import psutil
        for device, backend in self.manager.backends.items():
            state = read_json(self.manager.runtime / (device + '.process.json'), {})
            if not state.get('pid'):
                continue
            try:
                process = psutil.Process(state['pid'])
                command = process.cmdline()
                if (process.create_time() == state.get('created') and command == backend['command']
                        and any(Path(arg).is_absolute() and Path(arg).is_relative_to(source) for arg in command)):
                    process.terminate()
                    process.wait(timeout=15)
            except psutil.NoSuchProcess:
                pass

    def cleanup(self):
        with self.manager._lock, self.lock:
            self.setup.guard()
            if self.blocked() or not self.state.get('cleanup_pending'):
                raise RuntimeError('Перед очисткой полностью перезапустите приложение')
            source, target = local_folder(self.state['source']), local_folder(self.state['target'])
            current = Path(self.components.root if self.state['kind'] == 'components' else self.manager.value['workspace']).resolve()
            if current != target or overlaps(source, target) or source == self.here.resolve() or source in self.here.resolve().parents:
                raise ValueError('Новая папка ещё не используется; очистка запрещена')
            for root in (source, target):
                if read_json(root / '.storage-transfer.json', {}).get('token') != self.state.get('token'):
                    raise ValueError('Не подтверждена принадлежность папки этому переносу')
            self.active = True
            self.manager.operation = 'storage-cleanup'
            self.state.update(status='running', message='Проверяем обе копии перед очисткой старых файлов', bytes=0, total=0)
            self.save()
        threading.Thread(target=self.clean, name='storage-cleanup', daemon=True).start()
        return self.snapshot()

    def clean(self):
        source, target = Path(self.state['source']), Path(self.state['target'])
        try:
            with ExitStack() as stack:
                self.leases(stack, source, self.state['kind'])
                from release_lifecycle import busy
                if busy(source):
                    raise ValueError('Старая папка используется процессом. Завершите использующую её программу перед очисткой.')
                expected = {i['path']: i for i in self.state['files']}
                actual = files(source)
                if {p.relative_to(source).as_posix() for p in actual} - set(expected):
                    raise ValueError('В старой папке появились новые файлы. Автоматическая очистка отменена.')

                def verify(item):
                    old, new = source / item['path'], target / item['path']
                    if not old.resolve().is_relative_to(source) or not new.resolve().is_relative_to(target):
                        raise ValueError('Путь вышел за пределы папки переноса')
                    mutable = item['path'] in {'state.json', 'preparation.json'}
                    if ((old.exists() and digest(old) != item['source_hash']) or not new.is_file()
                            or (not mutable and digest(new) != item['target_hash'])):
                        raise ValueError('Одна из копий изменилась. Автоматическая очистка отменена; проверьте папки вручную.')
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(verify, expected.values()))
                self.state.update(message='Обе копии проверены. Удаляем старые файлы')
                # Only files verified above are removed, never a recursive deletion of a root.
                for path in actual:
                    path.unlink()
                (source / '.storage-transfer.json').unlink()
            for folder in sorted((p for p in source.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                if not any(folder.iterdir()):
                    folder.rmdir()
            self.state.update(status='done', cleanup_pending=False, message='Перенос завершён. Проверенные старые файлы удалены; новая папка используется приложением.')
        except (OSError, ValueError, RuntimeError) as exc:
            self.state.update(status='error', message='Очистка не завершена: ' + str(exc))
        finally:
            with self.manager._lock, self.lock:
                self.active = False
                self.manager.operation = None
                self.save()
