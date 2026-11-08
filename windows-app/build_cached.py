"""Complete offline installer, with the unchanged runtime compressed only once."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from build_release import HERE, ROOT, safe_member, sha256, source_paths
from component_cache import PREFIXES, digest, runtime_contract, validation_key
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename


def validate_lock(requirements, lock):
    versions = {str(parse_wheel_filename(item['file'])[0]): parse_wheel_filename(item['file'])[1] for item in lock}
    requested = {}
    for line in requirements.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith(('#', '--')):
            continue
        item = Requirement(line)
        if item.marker is None or item.marker.evaluate():
            requested[canonicalize_name(item.name)] = item.specifier
    if set(requested) != set(versions) or any(versions[name] not in spec for name, spec in requested.items()):
        raise ValueError('Requirements and pinned wheel hash lock do not match: ' + str(requirements))


def expected_contract():
    release = json.loads((HERE / 'release-inputs.json').read_text(encoding='utf-8'))
    component = json.loads((HERE / 'component-manifest.json').read_text(encoding='utf-8'))
    definitions = (HERE / 'WebView2Runtime.iss').read_text(encoding='utf-8')
    validate_lock(HERE / 'requirements-release.txt', json.loads((HERE / 'release-wheels.json').read_text(encoding='utf-8')))
    validate_lock(HERE / 'requirements-pyannote-cpu.lock', json.loads((HERE / 'domestic-wheels.json').read_text(encoding='utf-8')))
    return {
        'layout': 1, 'python': release['python']['sha256'], 'vcrt': release['vcrt']['sha256'],
        'wheels': sorted(json.loads((HERE / 'release-wheels.json').read_text(encoding='utf-8')), key=lambda x: x['file']),
        'component_manifest': sha256(HERE / 'component-manifest.json'),
        'whisper_revision': component['whisper_model']['revision'],
        'diarization_revision': component['diarization_model']['revision'],
        'diarization_wheels': sorted(json.loads((HERE / 'domestic-wheels.json').read_text(encoding='utf-8')), key=lambda x: x['file']),
        'webview_sha256': re.search(r'#define WebViewRuntimeSha256 "([^"]+)"', definitions)[1],
    }


def cache_components(cache, seed, domestic_inputs, seed_sha=None):
    key = digest(expected_contract())
    destination = cache / 'component-bundles' / key
    record_file = destination / 'cache.json'
    if record_file.is_file():
        try:
            record = json.loads(record_file.read_text(encoding='utf-8'))
            if record['key'] == key and sha256(destination / 'components.zip') == record['archive_sha256']:
                print('CACHE HIT: verified Python, libraries and models; no unpacking or recompression', flush=True)
                return destination, record
        except (OSError, ValueError, KeyError):
            pass
    print('CACHE MISS: preparing and verifying runtime once', flush=True)
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='vd-component-seed-') as temporary:
        if seed:
            if seed_sha and sha256(seed) != seed_sha:
                raise ValueError('Accepted full seed archive checksum mismatch')
            with zipfile.ZipFile(seed) as archive:
                base = json.loads(archive.read('release-manifest.json'))
            if digest(runtime_contract(base)) != key:
                seed = None
        if not seed:
            if not domestic_inputs:
                raise ValueError('Cold component cache requires --domestic-inputs')
            subprocess.run([sys.executable, str(HERE / 'build_release.py'), '--domestic',
                            '--domestic-inputs', str(domestic_inputs), '--cache', str(cache),
                            '--output', temporary], check=True)
            seed = next(Path(temporary).glob('*.zip'))
        with zipfile.ZipFile(seed) as archive:
            base = json.loads(archive.read('release-manifest.json'))
            if digest(runtime_contract(base)) != key:
                raise ValueError('Runtime seed does not match pinned component inputs')
            entries = [item for item in base['files'] if item['path'].startswith(PREFIXES)]
            partial = destination / 'components.zip.partial'
            try:
                with zipfile.ZipFile(partial, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as target:
                    for index, item in enumerate(entries, 1):
                        name = safe_member(item['path']).as_posix()
                        payload = archive.read(name)
                        if hashlib.sha256(payload).hexdigest() != item['sha256']:
                            raise ValueError('Seed checksum mismatch: ' + name)
                        info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
                        info.compress_type = zipfile.ZIP_DEFLATED
                        info.create_system = 3
                        info.external_attr = 0o644 << 16
                        target.writestr(info, payload, compresslevel=6)
                        if index % 4000 == 0:
                            print(f'Component cache: verified/compressed {index}/{len(entries)} files', flush=True)
                partial.replace(destination / 'components.zip')
            finally:
                partial.unlink(missing_ok=True)
    record = {'key': key, 'archive_sha256': sha256(destination / 'components.zip'), 'files': entries,
              'domestic': base['domestic'], 'python_source': base['python_source'],
              'vcrt_source': base['vcrt_source'], 'wheels': base['wheels']}
    record_file.write_text(json.dumps(record, indent=2), encoding='utf-8')
    return destination, record


def build(cache, output, iscc, seed=None, domestic_inputs=None, seed_sha=None):
    bundle, record = cache_components(cache, seed, domestic_inputs, seed_sha)
    release = json.loads((HERE / 'release-inputs.json').read_text(encoding='utf-8'))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='vd-cached-app-') as temporary:
        app = Path(temporary)
        for source in source_paths():
            target = app / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        for name in ('domestic_setup.py', 'component_cache.py'):
            shutil.copyfile(HERE / name, app / 'windows-app' / name)
        sdk = HERE / 'runtime/desktop-sdk'
        metadata = json.loads((sdk / 'desktop-build.json').read_text(encoding='utf-8'))
        if metadata != {'source_sha256': sha256(HERE / 'DesktopHost.cs'), 'sdk_sha256': release['webview2']['sha256']}:
            raise ValueError('Desktop SDK is stale; run Prepare-Desktop.ps1')
        shutil.copytree(sdk, app / 'windows-app/desktop-sdk')
        (app / 'Prepare Domestic.cmd').write_text(
            '@echo off\r\n"%~dp0python\\python.exe" -X utf8 "%~dp0windows-app\\domestic_setup.py"\r\n', encoding='ascii')
        (app / 'Open Video Descriptor.cmd').write_text(
            '@echo off\r\ncall "%~dp0Prepare Domestic.cmd"\r\nif errorlevel 1 exit /b 1\r\n'
            'call "%~dp0windows-app\\Open-App.cmd"\r\n', encoding='ascii')
        files = [{'path': p.relative_to(app).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha256(p)}
                 for p in sorted(app.rglob('*')) if p.is_file()]
        manifest = {**{name: record[name] for name in ('domestic', 'python_source', 'vcrt_source', 'wheels')},
                    'version': release['version'], 'architecture': 'windows-x64', 'profile': 'domestic',
                    'whisper_weights_included': True, 'component_cache_key': record['key'],
                    'files': sorted([*record['files'], *files], key=lambda item: item['path'])}
        manifest['component_validation_key'] = validation_key(manifest)
        (app / 'release-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(f'Building complete offline EXE: {len(files)} app files plus cached runtime '
              f'({len(record["files"])} files); runtime stored without recompression', flush=True)
        subprocess.run([str(iscc), f'/DPayload={app}', f'/DAppVersion={release["version"]}',
                        '/DDomestic=1', f'/DCachedComponents={bundle}',
                        f'/DComponentsSize={sum(item["bytes"] for item in record["files"])}',
                        f'/O{output.resolve()}', str(HERE / 'installer.iss')], check=True)
        # Small verification input only; published artifact remains a single full EXE.
        with zipfile.ZipFile(output / 'app-payload.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(app.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(app).as_posix())
        (output / 'cache-reference.json').write_text(json.dumps(
            {'bundle': str(bundle), 'key': record['key'], 'archive_sha256': record['archive_sha256']}), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--iscc', type=Path, required=True)
    parser.add_argument('--seed', type=Path)
    parser.add_argument('--seed-sha')
    parser.add_argument('--domestic-inputs', type=Path)
    args = parser.parse_args()
    build(args.cache, args.output, args.iscc, args.seed, args.domestic_inputs, args.seed_sha)
