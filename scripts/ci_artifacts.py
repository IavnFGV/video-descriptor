"""Verify exact release inputs; do not substitute rebuilt binaries for published assets."""
import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    entries = json.loads((ROOT / 'dist/SHA256SUMS.json').read_text(encoding='utf-8'))
    version = json.loads((ROOT / 'windows-app/release-inputs.json').read_text())['version']
    expected = {f'VideoDescriptor-{version}-windows-x64.zip', f'VideoDescriptor-{version}-windows-x64-setup.exe'}
    assert {entry['file'] for entry in entries} == expected, 'Release must supply ZIP and installer checksums'
    for entry in entries:
        path = ROOT / 'dist' / entry['file']
        assert path.name == entry['file'], 'Unsafe asset path'
        with path.open('rb') as source:
            assert hashlib.file_digest(source, 'sha256').hexdigest() == entry['sha256'], path.name
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    with zipfile.ZipFile(ROOT / f'dist/VideoDescriptor-{version}-windows-x64.zip') as archive:
        manifest = json.loads(archive.read('release-manifest.json'))
    provenance_path = ROOT / 'dist/acceptance-provenance.json'
    if args.record:
        provenance_path.write_text(json.dumps({'git_sha': revision, 'artifacts': entries}, indent=2), encoding='utf-8')
    provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
    assert provenance['git_sha'] == revision, 'Release artifact does not belong to the checked-out tag revision'
    assert provenance['artifacts'] == entries, 'Release hashes differ from accepted artifacts'
    assert manifest['version'] == version
    print('PASS: exact artifact checksums and source revision', revision)


if __name__ == '__main__':
    main()
