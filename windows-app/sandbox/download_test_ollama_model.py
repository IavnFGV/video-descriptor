"""Create a dedicated public test model store from verified registry blobs.

No local user model directories are read. The caller must pin the registry manifest.
"""
import argparse
import concurrent.futures
import hashlib
import json
import re
from pathlib import Path

import requests


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download_blob(root, item):
    digest = item['digest']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest) or not 0 < item['size'] < 20 * 1024**3:
        raise ValueError('Invalid public registry blob descriptor')
    target = root / 'blobs' / digest.replace(':', '-')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError('Test model blobs must not be links')
    if target.is_file() and target.stat().st_size == item['size'] and checksum(target) == digest[7:]:
        return
    partial = target.with_suffix('.partial')
    url = 'https://registry.ollama.ai/v2/library/' + root.name + '/blobs/' + digest
    count = 0
    with requests.get(url, stream=True, timeout=(15, 60)) as response:
        response.raise_for_status()
        with partial.open('wb') as output:
            for block in response.iter_content(2 * 1024**2):
                count += len(block)
                if count > item['size']:
                    raise ValueError('Registry blob exceeds its declared size')
                output.write(block)
    if count != item['size'] or checksum(partial) != digest[7:]:
        raise ValueError('Registry blob integrity mismatch')
    partial.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9_.-]+:[a-z0-9_.-]+', args.model):
        parser.error('Only explicit public library model:tag names are accepted')
    name, tag = args.model.split(':')
    url = f'https://registry.ollama.ai/v2/library/{name}/manifests/{tag}'
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    digest = hashlib.sha256(response.content).hexdigest()
    if digest != args.manifest_sha256:
        raise ValueError('Public model tag changed from the explicitly pinned manifest')
    manifest = response.json()
    root = args.destination / name
    root.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda item: download_blob(root, item), [manifest['config'], *manifest['layers']]))
    target = root / 'manifests/registry.ollama.ai/library' / name / tag
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(response.content)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'model': args.model, 'source': url, 'manifest_sha256': digest,
                                      'model_directory': str(root.resolve()), 'blobs_verified': len(manifest['layers']) + 1}, indent=2), encoding='utf-8')
    print(root.resolve())


if __name__ == '__main__':
    main()
