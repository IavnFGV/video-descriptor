"""Fetch/reuse only the pinned official public Whisper acceptance fixture."""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from model_download import download_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    profile = json.loads((HERE / 'component-manifest.json').read_text(encoding='utf-8'))['whisper_model']
    target = args.destination / ('whisper-small-' + profile['revision'])
    if target.is_symlink() or target.is_junction():
        raise ValueError('Public test model cache must not contain links')
    if target.exists():
        from model_download import checksum
        for item in profile['files']:
            path = target / item['name']
            if path.stat().st_size != item['bytes'] or checksum(path) != item['sha256']:
                raise ValueError('Existing public test model is corrupt: ' + item['name'])
    else:
        staging, target = download_profile(profile, args.destination, lambda *_: None)
        staging.rename(target)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'model_directory': str(target.resolve()), 'revision': profile['revision'],
                                     'source': profile['source'], 'files': profile['files']}, indent=2), encoding='utf-8')
    print(target.resolve())


if __name__ == '__main__':
    main()
