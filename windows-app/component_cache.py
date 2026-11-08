"""Content-addressed, precompressed runtime shared by complete offline installers."""
import argparse
import hashlib
import json
from pathlib import Path

PREFIXES = ('python/', 'windows-app/domestic/')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def runtime_contract(manifest):
    domestic = manifest['domestic']
    return {
        'layout': 1,
        'python': manifest['python_source']['sha256'], 'vcrt': manifest['vcrt_source']['sha256'],
        'wheels': sorted(manifest['wheels'], key=lambda item: item['file']),
        'component_manifest': next(item['sha256'] for item in manifest['files']
                                   if item['path'] == 'windows-app/component-manifest.json'),
        'whisper_revision': domestic['whisper_revision'], 'diarization_revision': domestic['diarization_revision'],
        'diarization_wheels': sorted(domestic['wheels'], key=lambda item: item['file']),
        'webview_sha256': domestic['webview_sha256'],
    }


def validation_key(manifest):
    names = {'windows-app/whisper_worker.py', 'windows-app/diarization_worker.py',
             'windows-app/domestic_setup.py', 'windows-app/component_manager.py',
             'windows-app/compute.py', 'windows-app/setup_service.py', 'windows-app/component_cache.py'}
    return digest({'runtime': manifest['component_cache_key'],
                   'code': sorted((item['path'], item['sha256']) for item in manifest['files'] if item['path'] in names)})


def reusable_install(root, expected):
    """Reuse only an identified, prepared install; no model loads and no writes."""
    root = Path(root).resolve()
    try:
        previous = json.loads((root / 'release-manifest.json').read_text(encoding='utf-8'))
        marker = json.loads((root / 'windows-app/runtime/domestic-setup.json').read_text(encoding='utf-8'))
        if (digest(runtime_contract(previous)) != expected['component_cache_key'] or
                marker.get('root') != str(root) or
                not (root / 'windows-app/config.local.json').is_file()):
            return False
        # Verify core executables and every file's presence/size. Unlike rehashing
        # 31k files this reads metadata only; runtime checks still gate actual jobs.
        for entry in expected['files']:
            if not entry['path'].startswith(PREFIXES):
                continue
            path = root / entry['path']
            if not path.resolve().is_relative_to(root) or path.stat().st_size != entry['bytes']:
                return False
            if entry['path'] in {'python/python.exe', 'python/python312.dll'}:
                with path.open('rb') as source:
                    if hashlib.file_digest(source, 'sha256').hexdigest() != entry['sha256']:
                        return False
        return True
    except (OSError, ValueError, KeyError, StopIteration):
        return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if reusable_install(args.root, json.loads(args.manifest.read_text(encoding='utf-8'))) else 1)
