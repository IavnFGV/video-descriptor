"""Pinned actionlint; a small validator download, never an AI/runtime installation."""
import hashlib
import io
import os
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = '1.7.7'
ARCHIVES = {
    'nt': ('windows_amd64.zip', '7f12f1801bca3d480d67aaf7774f4c2a6359a3ca8eebe382c95c10c9704aa731'),
    'posix': ('linux_amd64.tar.gz', '023070a287cd8cccd71515fedc843f1985bf96c436b7effaecce67290e7e0757'),
}


def main():
    root = Path(__file__).resolve().parents[1]
    suffix, expected = ARCHIVES[os.name]
    name = f'actionlint_{VERSION}_{suffix}'
    cache = root / 'windows-app/runtime/ci-tools'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / name
    if not archive.exists():
        urllib.request.urlretrieve(f'https://github.com/rhysd/actionlint/releases/download/v{VERSION}/{name}', archive)
    data = archive.read_bytes()
    assert hashlib.sha256(data).hexdigest() == expected, 'actionlint archive checksum mismatch'
    binary = 'actionlint.exe' if os.name == 'nt' else 'actionlint'
    if os.name == 'nt':
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            payload = package.read(binary)
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as package:
            payload = package.extractfile(binary).read()
    executable = cache / binary
    executable.write_bytes(payload)
    executable.chmod(0o755)
    workflows = sorted((root / '.github/workflows').glob('*.yml'))
    subprocess.run([str(executable), '-shellcheck=', '-pyflakes=', *map(str, workflows)], cwd=root, check=True)


if __name__ == '__main__':
    main()
