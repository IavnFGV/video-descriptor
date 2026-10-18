"""Build a private Windows preview from explicit source files and pinned wheel inputs."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from email.parser import BytesParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def sha256(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def download(item, cache):
    target = cache / item['url'].rsplit('/', 1)[-1]
    if not target.exists():
        partial = target.with_suffix('.partial')
        urllib.request.urlretrieve(item['url'], partial)
        partial.replace(target)
    if sha256(target) != item['sha256']:
        raise ValueError('Input checksum mismatch: ' + target.name)
    return target


def safe_member(name):
    path = Path(name)
    if path.anchor or '..' in path.parts or ':' in name or '\\' in name:
        raise ValueError('Unsafe archive entry: ' + name)
    return path


def unpack_wheels(wheels, destination):
    """Vendor library payloads and notices; do not generate machine-specific CLI wrappers."""
    for wheel in sorted(wheels):
        with zipfile.ZipFile(wheel) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                path = safe_member(member.filename)
                if path.parts[0].endswith('.data'):
                    if path.parts[1] not in {'purelib', 'platlib'}:
                        continue
                    path = Path(*path.parts[2:])
                target = destination / path
                payload = archive.read(member)
                if target.exists() and target.read_bytes() != payload:
                    raise ValueError('Conflicting wheel payload: ' + str(path))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)


def resolved_wheels(directory, requirements):
    pins = {line.strip().lower().replace('_', '-').split('==')[0]: line.strip().split('==')[1]
            for line in requirements.read_text().splitlines() if line.strip() and not line.startswith('#')}
    resolved = {}
    for path in sorted(directory.glob('*.whl')):
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
            if len(names) != 1:
                raise ValueError('Invalid wheel metadata: ' + path.name)
            metadata = BytesParser().parsebytes(archive.read(names[0]))
        name = metadata['Name'].lower().replace('_', '-')
        if pins.get(name) != metadata['Version']:
            continue  # Old/unrelated cache entries are never release inputs.
        if name in resolved:
            raise ValueError('Ambiguous wheel builds: ' + name)
        resolved[name] = path
    if set(resolved) != set(pins):
        raise ValueError('Missing exact pinned wheels: ' + ', '.join(sorted(set(pins) - set(resolved))))
    return sorted(resolved.values())


def deterministic_zip(folder, output):
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                info = zipfile.ZipInfo(path.relative_to(folder).as_posix(), (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes(), compresslevel=6)


def source_paths():
    # No repository-wide archive/glob: runtime, env, media, models and old results stay out.
    paths = list((ROOT / 'video_descriptor').rglob('*.py'))
    paths += [p for name in ('assets', 'prompts') for p in (ROOT / 'video_descriptor' / name).rglob('*') if p.is_file()]
    paths += [HERE / name for name in (
        'app.py', 'compute.py', 'setup_service.py', 'whisper_worker.py', 'release_lifecycle.py',
        'desktop.py', 'Desktop.ps1', 'DesktopHost.cs', 'app.ico',
        'Start-App.ps1', 'Open-App.cmd', 'config.example.json', 'README.md', 'THIRD-PARTY.md',
        'component-manifest.json', 'release-inputs.json', 'requirements-release.txt')]
    paths += [p for p in (HERE / 'ui').iterdir() if p.is_file()]
    paths += [ROOT / 'scripts/whisper_npu_server.py', ROOT / 'README.md']
    paths += [ROOT / 'docs' / name for name in ('architecture-windows.md', 'device-policy-and-release.md',
                                               'competitive-analysis.md', 'verification-devices.md',
                                               'verification-devices.json', 'windows-release.md',
                                               'desktop-windows.md')]
    return sorted({p for p in paths if '__pycache__' not in p.parts})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=HERE / 'runtime/build-cache')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--iscc', type=Path)
    parser.add_argument('--refresh-lock', action='store_true', help='Explicitly record hashes after resolving pinned wheels')
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    inputs = json.loads((HERE / 'release-inputs.json').read_text())
    python_zip = download(inputs['python'], args.cache)
    wheel_dir = args.cache / 'wheels'
    wheel_dir.mkdir(exist_ok=True)
    lock_file = HERE / 'release-wheels.json'
    if args.refresh_lock or not lock_file.exists():
        if not args.refresh_lock:
            raise ValueError('Missing wheel hash lock; explicitly use --refresh-lock to record inputs')
        subprocess.run([sys.executable, '-m', 'pip', 'download', '--only-binary=:all:', '--dest', str(wheel_dir),
                        '-r', str(HERE / 'requirements-release.txt')], check=True)
        lock = [{'file': p.name, 'sha256': sha256(p)} for p in resolved_wheels(wheel_dir, HERE / 'requirements-release.txt')]
        lock_file.write_text(json.dumps(lock, indent=2) + '\n', encoding='utf-8')
    lock = json.loads(lock_file.read_text())
    # Fresh CI caches resolve only exact versions, then verify the previously reviewed bytes.
    if any(not (wheel_dir / entry['file']).exists() for entry in lock):
        subprocess.run([sys.executable, '-m', 'pip', 'download', '--only-binary=:all:', '--dest', str(wheel_dir),
                        '-r', str(HERE / 'requirements-release.txt')], check=True)
    wheels = []
    for entry in lock:
        path = wheel_dir / safe_member(entry['file'])
        if sha256(path) != entry['sha256']:
            raise ValueError('Wheel checksum mismatch: ' + path.name)
        wheels.append(path)
    if {p.name for p in resolved_wheels(wheel_dir, HERE / 'requirements-release.txt')} != {p.name for p in wheels}:
        raise ValueError('Wheel hash lock and requirements do not match')
    # A new directory per build: never recursively erase a computed user path.
    import tempfile
    folder = Path(tempfile.mkdtemp(prefix='payload-', dir=args.cache))
    for path in source_paths():
        target = folder / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    shutil.copyfile(lock_file, folder / 'windows-app/release-wheels.json')
    python_dir = folder / 'python'
    python_dir.mkdir()
    with zipfile.ZipFile(python_zip) as archive:
        for member in archive.infolist():
            safe_member(member.filename)
        archive.extractall(python_dir)
    unpack_wheels(wheels, python_dir / 'Lib/site-packages')
    sdk = HERE / 'runtime/desktop-sdk'
    if not (sdk / 'VideoDescriptor.exe').is_file():
        raise ValueError('Run windows-app/Prepare-Desktop.ps1 before building the desktop preview')
    desktop_build = json.loads((sdk / 'desktop-build.json').read_text())
    if (desktop_build['source_sha256'] != sha256(HERE / 'DesktopHost.cs')
            or desktop_build['sdk_sha256'] != inputs['webview2']['sha256']):
        raise ValueError('Desktop build is stale; run windows-app/Prepare-Desktop.ps1')
    shutil.copytree(sdk, folder / 'windows-app/desktop-sdk')
    (python_dir / 'python312._pth').write_text('python312.zip\n.\nLib/site-packages\n..\n../windows-app\nimport site\n', encoding='ascii')
    # Keep packaged subprocesses on this runtime; ignore system PYTHONPATH/registry.
    (folder / 'Open Video Descriptor.cmd').write_text('@echo off\r\ncall "%~dp0windows-app\\Open-App.cmd"\r\n', encoding='ascii')
    entries = [{'path': p.relative_to(folder).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha256(p)}
               for p in sorted(folder.rglob('*')) if p.is_file()]
    manifest = {'version': inputs['version'], 'architecture': 'windows-x64', 'whisper_weights_included': False,
                'vad_asset_in_faster_whisper': True,
                'python_source': inputs['python'], 'wheels': lock, 'files': entries}
    (folder / 'release-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    output = args.output / f'VideoDescriptor-{inputs["version"]}-windows-x64.zip'
    deterministic_zip(folder, output)
    print('ZIP:', output, 'SHA256:', sha256(output), flush=True)
    if args.iscc:
        subprocess.run([str(args.iscc), '/Qp', f'/DPayload={folder}', f'/DAppVersion={inputs["version"]}',
                        f'/O{args.output.resolve()}', str(HERE / 'installer.iss')], check=True)
    artifacts = [{'file': p.name, 'bytes': p.stat().st_size, 'sha256': sha256(p)}
                 for p in sorted(args.output.glob(f'VideoDescriptor-{inputs["version"]}-windows-x64*'))]
    (args.output / 'SHA256SUMS.json').write_text(json.dumps(artifacts, indent=2) + '\n', encoding='utf-8')
    print('Payload:', folder, flush=True)


if __name__ == '__main__':
    main()
