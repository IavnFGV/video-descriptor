"""Downloader for one pinned official Whisper profile, without archive extraction."""
import hashlib
import os
import shutil
from pathlib import Path

import requests


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def download_profile(profile, root, progress):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    revision = profile['revision']
    if len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
        raise ValueError('Invalid pinned revision')
    staging = root / ('.whisper-small-' + revision + '.partial')
    target = root / ('whisper-small-' + revision)
    for folder in (staging, target):
        if folder.is_symlink() or folder.is_junction():
            raise ValueError('Model directory must not be a link')
    staging.mkdir(exist_ok=True)
    total = sum(item['bytes'] for item in profile['files'])
    if shutil.disk_usage(root).free < total + 64 * 1024**2:
        raise ValueError('Недостаточно места: нужно около 550 МиБ свободного места')
    done = 0
    with requests.Session() as session:
        session.trust_env = False
        for item in profile['files']:
            name = item['name']
            if not name or Path(name).name != name or any(c in name for c in '/\\:') or name in {'.', '..'}:
                raise ValueError('Unsafe model filename')
            destination = staging / name
            temporary = staging / (name + '.part')
            if destination.is_symlink() or temporary.is_symlink():
                raise ValueError('Model files must not be links')
            if destination.is_file() and destination.stat().st_size == item['bytes'] and checksum(destination) == item['sha256']:
                done += item['bytes']
                progress(done, total, name)
                continue
            # Restart only the interrupted file; retain completed, verified files.
            with session.get(profile['source'] + '/resolve/' + revision + '/' + name,
                             stream=True, timeout=(10, 30)) as response:
                response.raise_for_status()
                count = 0
                with temporary.open('wb') as output:
                    for block in response.iter_content(1024 * 1024):
                        count += len(block)
                        if count > item['bytes']:
                            raise ValueError('Размер файла модели превышает манифест')
                        output.write(block)
                        progress(done + count, total, name)
                    output.flush()
                    os.fsync(output.fileno())
            if count != item['bytes'] or checksum(temporary) != item['sha256']:
                raise ValueError('Не совпала контрольная сумма или размер файла ' + name)
            temporary.replace(destination)
            done += count
    return staging, target
