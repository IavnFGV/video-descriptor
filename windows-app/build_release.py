"""Build a private Windows preview from explicit source files and pinned wheel inputs."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from contextlib import ExitStack
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


def unpack_wheels(wheels, destination, cached_files=None):
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
                if cached_files is not None:
                    cached_files[target] = {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(),
                                            'archive': wheel, 'member': member.filename}


def resolved_wheels(directory, requirements):
    pins = {line.strip().lower().replace('_', '-').split('==')[0]: line.strip().split('==')[1]
            for line in requirements.read_text().splitlines() if line.strip() and not line.startswith(('#', '--'))}
    resolved = {}
    for path in sorted(directory.glob('*.whl')):
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA') and n.count('/') == 1]
            if len(names) != 1:
                raise ValueError('Invalid wheel metadata: ' + path.name)
            metadata = BytesParser().parsebytes(archive.read(names[0]))
        name = metadata['Name'].lower().replace('_', '-')
        version = metadata['Version']
        pin = pins.get(name)
        if pin != version and not (pin and '+' not in pin and version.split('+')[0] == pin):
            continue  # Old/unrelated cache entries are never release inputs.
        if name in resolved:
            raise ValueError('Ambiguous wheel builds: ' + name)
        resolved[name] = path
    if set(resolved) != set(pins):
        raise ValueError('Missing exact pinned wheels: ' + ', '.join(sorted(set(pins) - set(resolved))))
    return sorted(resolved.values())


def deterministic_zip(folder, output, cached_files=None):
    with ExitStack() as stack:
        archive = stack.enter_context(zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6))
        sources = {}
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                info = zipfile.ZipInfo(path.relative_to(folder).as_posix(), (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                cached = (cached_files or {}).get(path)
                if cached:
                    source = cached['archive']
                    if source not in sources:
                        sources[source] = stack.enter_context(zipfile.ZipFile(source))
                    payload = sources[source].read(cached['member'])
                    if hashlib.sha256(payload).hexdigest() != cached['sha256']:
                        raise ValueError('Archive changed during build: ' + str(source))
                else:
                    payload = path.read_bytes()
                archive.writestr(info, payload, compresslevel=6)


def source_paths():
    # No repository-wide archive/glob: runtime, env, media, models and old results stay out.
    paths = list((ROOT / 'video_descriptor').rglob('*.py'))
    paths += [p for name in ('assets', 'prompts') for p in (ROOT / 'video_descriptor' / name).rglob('*') if p.is_file()]
    paths += [HERE / name for name in (
        'app.py', 'compute.py', 'component_manager.py', 'storage_service.py', 'install_packages.py', 'setup_service.py', 'model_download.py', 'whisper_worker.py', 'release_lifecycle.py',
        'requirements-pyannote-cpu.lock', 'requirements-pyannote-xpu.lock',
        'diarization_worker.py', 'diarization_setup.py', 'Prepare-Diarization.ps1',
        'desktop.py', 'Desktop.ps1', 'DesktopHost.cs', 'app.ico',
        'Start-App.ps1', 'Ensure-WebView2.ps1', 'Open-App.cmd', 'config.example.json', 'README.md', 'THIRD-PARTY.md',
        'component-manifest.json', 'release-inputs.json', 'requirements-release.txt')]
    paths += [p for p in (HERE / 'ui').iterdir() if p.is_file()]
    paths += [HERE / 'samples' / name for name in ('speech-check.wav', 'speech-check.mp4', 'README.md')]
    paths += [ROOT / 'scripts/whisper_npu_server.py', ROOT / 'README.md',
              ROOT / 'requirements-diarization.txt', ROOT / 'requirements-diarization-xpu.txt']
    paths += [ROOT / 'docs' / name for name in ('architecture-windows.md', 'device-policy-and-release.md',
                                               'competitive-analysis.md', 'verification-devices.md',
                                               'verification-devices.json', 'windows-release.md',
                                               'desktop-windows.md', 'ai-setup-windows.md', 'ai-component-manager.md', 'native-diarization.md')]
    return sorted({p for p in paths if '__pycache__' not in p.parts})


def expand_cabinet(cabinet, destination):
    # Git hooks prepend Git's usr/bin, which contains a different expand.exe
    # (GNU tab expansion). CAB extraction must use the Windows inbox utility.
    executable = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/expand.exe'
    result = subprocess.run([str(executable), '-F:*', str(cabinet), str(destination)],
                            check=False, capture_output=True)
    if result.returncode:
        detail = (result.stdout + result.stderr).decode('utf-8', errors='replace')[-2000:]
        raise RuntimeError(f'Windows CAB extraction failed ({result.returncode}): {detail}')


def stage_vcrt(inputs, cache, destination):
    """App-local Microsoft CRT from reviewed bytes; never install a host prerequisite."""
    import tempfile

    dotnet = shutil.which('dotnet')
    if not dotnet:
        raise ValueError('Building the app-local VC runtime requires an existing .NET 8+ runtime')
    runtime = download(inputs['vcrt'], cache)
    wix_package = download(inputs['vcrt_extractor'], cache)
    with tempfile.TemporaryDirectory(prefix='vcrt-', dir=cache) as temporary:
        work = Path(temporary)
        wix = work / 'wix'
        with zipfile.ZipFile(wix_package) as archive:
            for member in archive.infolist():
                safe_member(member.filename)
            archive.extractall(wix)
        # WiX 6 targets net6.0; allow the installed build-machine .NET 8+ runtime.
        env = dict(os.environ, DOTNET_ROLL_FORWARD='Major')
        subprocess.run([dotnet, str(wix / 'tools/net6.0/any/wix.dll'), 'burn', 'extract',
                        str(runtime.resolve()), '-o', str((work / 'bundle').resolve()),
                        '-oba', str((work / 'bootstrapper').resolve())], check=True, env=env)
        extracted = work / 'crt'
        extracted.mkdir()
        expand_cabinet(work / 'bundle' / inputs['vcrt']['cabinet'], extracted)
        for item in inputs['vcrt']['files']:
            name = item['name']
            safe_member(name)
            source = extracted / (name + '_amd64')
            if sha256(source) != item['sha256']:
                raise ValueError('VC runtime checksum mismatch: ' + name)
            shutil.copyfile(source, destination / name)
        license_file = work / 'bootstrapper/license.rtf'
        if sha256(license_file) != inputs['vcrt']['license_sha256']:
            raise ValueError('VC runtime license checksum mismatch')
        shutil.copyfile(license_file, destination / 'Microsoft-Visual-Cpp-LICENSE.rtf')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=HERE / 'runtime/build-cache')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--iscc', type=Path)
    parser.add_argument('--domestic', action='store_true', help='Bundle offline speech and CPU diarization inputs')
    parser.add_argument('--domestic-inputs', type=Path, help='Local JSON paths to verified models, CPU wheelhouse and WebView2 CAB')
    parser.add_argument('--refresh-lock', action='store_true', help='Explicitly record hashes after resolving pinned wheels')
    args = parser.parse_args()
    if args.domestic and not args.domestic_inputs:
        parser.error('--domestic requires --domestic-inputs; incomplete domestic builds are not allowed')
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
    with tempfile.TemporaryDirectory(prefix='payload-', dir=args.cache) as temporary:
        folder = Path(temporary)
        cached_files = {}
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
        unpack_wheels(wheels, python_dir / 'Lib/site-packages', cached_files)
        stage_vcrt(inputs, args.cache, python_dir)
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
        domestic = None
        if args.domestic:
            from domestic_bundle import stage
            domestic = stage(folder, args.domestic_inputs, python_zip, cached_files)
        print('Recording payload manifest', flush=True)
        entries = [{'path': p.relative_to(folder).as_posix(),
                    'bytes': cached_files[p]['bytes'] if p in cached_files else p.stat().st_size,
                    'sha256': cached_files[p]['sha256'] if p in cached_files else sha256(p)}
                   for p in sorted(folder.rglob('*')) if p.is_file()]
        manifest = {'version': inputs['version'], 'architecture': 'windows-x64', 'whisper_weights_included': args.domestic,
                    'profile': 'domestic' if args.domestic else 'standard', 'domestic': domestic,
                    'vad_asset_in_faster_whisper': True,
                    'python_source': inputs['python'], 'vcrt_source': inputs['vcrt'],
                    'wheels': lock, 'files': entries}
        (folder / 'release-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        output = args.output / f'VideoDescriptor-{inputs["version"]}-windows-x64.zip'
        print('Writing reproducible ZIP', flush=True)
        deterministic_zip(folder, output, cached_files)
        print('ZIP:', output, 'SHA256:', sha256(output), flush=True)
        if args.iscc:
            print('Building Windows installer (Inno Setup)', flush=True)
            subprocess.run([str(args.iscc), f'/DPayload={folder}', f'/DAppVersion={inputs["version"]}',
                            *(['/DDomestic=1'] if args.domestic else []),
                            f'/O{args.output.resolve()}', str(HERE / 'installer.iss')], check=True)
        artifacts = [{'file': p.name, 'bytes': p.stat().st_size, 'sha256': sha256(p)}
                     for p in sorted(args.output.glob(f'VideoDescriptor-{inputs["version"]}-windows-x64*'))]
        (args.output / 'SHA256SUMS.json').write_text(json.dumps(artifacts, indent=2) + '\n', encoding='utf-8')
        print('Packaging complete; temporary payload is being removed', flush=True)


if __name__ == '__main__':
    main()
