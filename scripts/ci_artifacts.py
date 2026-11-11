"""Verify exact release inputs; do not substitute rebuilt binaries for published assets."""
import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Dependency assets from the pinned wheels, not downloadable speech/diarization/LLM bundles.
APPROVED_ONNX = {
    'python/Lib/site-packages/faster_whisper/assets/silero_vad_v6.onnx': '4cbf549b8326f60f80f2536d9eefeb450a9abe83365a098031c89719f1be17d2',
    'python/Lib/site-packages/onnxruntime/datasets/logreg_iris.onnx': '8224784c98d73412d9fd99abcd57a38568bd590980d0fbe5916464531c52e8fc',
    'python/Lib/site-packages/onnxruntime/datasets/mul_1.onnx': '71f431c4e9321ec6fbeb158d02ed240459a7dcc98673fa79a4f439ce42efaf10',
    'python/Lib/site-packages/onnxruntime/datasets/sigmoid.onnx': '5340aba67a7e3475162ad794378af55f1718f55f9a5d74b4af60ecc7f7a624b6',
}
DEPENDENCY_MODEL_CODE = tuple('python/Lib/site-packages/' + name for name in (
    'ctranslate2/models/', 'onnxruntime/transformers/models/', 'tokenizers/models/'))


def require_public_payload(manifest, names):
    """Publication boundary, independent of filenames and the build cache location."""
    if (manifest.get('profile') != 'standard' or manifest.get('domestic') is not None
            or manifest.get('whisper_weights_included') is not False
            or 'component_cache_key' in manifest):
        raise ValueError('Public releases require the standard package; Domestic/cached model bundles are private')
    for name in names:
        normalized = name.replace('\\', '/').lower()
        parts = normalized.split('/')
        dependency_code = name.startswith(DEPENDENCY_MODEL_CODE) and name.endswith(('.py', '.pyi'))
        if (normalized.startswith('/') or '..' in parts or ':' in normalized
                or any(part in {'domestic', 'model-cache', '.cache', '.env', '.huggingface'} for part in parts)
                or ('models' in parts and not dependency_code)
                or parts[-1].startswith('.env') or parts[-1] in {'config.local.json', 'components.zip', 'cache-reference.json',
                                                                             'domestic_setup.py', 'domestic-manifest.json'}
                or normalized.endswith(('.gguf', '.safetensors', '.pt', '.pth', '.ckpt', '.bin'))
                or (normalized.endswith('.onnx') and name not in APPROVED_ONNX)
                or parts[-1] in {'model.bin', 'pytorch_model.bin', 'openvino_model.bin', 'plda.npz', 'xvec_transform.npz'}):
            raise ValueError('Private/model payload cannot be published: ' + name)


def check_public_zip(archive):
    manifest = json.loads(archive.read('release-manifest.json'))
    if 'build' in manifest and (type(manifest['build']) is not int or manifest['build'] < 1
                                or int(archive.read('BUILD').decode('ascii').strip()) != manifest['build']):
        raise ValueError('Packaged build number differs from the release manifest')
    require_public_payload(manifest, archive.namelist())
    expected = {item['path'] for item in manifest['files']} | {'release-manifest.json'}
    names = archive.namelist()
    if len(names) != len(set(names)) or set(names) != expected:
        raise ValueError('Public ZIP contains duplicate, missing or unlisted payload entries')
    for name, digest in APPROVED_ONNX.items():
        if name in names and hashlib.sha256(archive.read(name)).hexdigest() != digest:
            raise ValueError('Unreviewed dependency model bytes: ' + name)
    if (any('faster_whisper/assets/' in name for name in names)
            and 'windows-app/licenses/SILERO-VAD-LICENSE.txt' not in names):
        raise ValueError('Public VAD dependency requires the Silero license notice')
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build-qualified', action='store_true')
    parser.add_argument('--record', action='store_true')
    parser.add_argument('--directory', type=Path, help='Exact accepted assets directory; default: dist')
    args = parser.parse_args()
    directory = args.directory or ROOT / 'dist'
    entries = json.loads((directory / 'SHA256SUMS.json').read_text(encoding='utf-8'))
    version = json.loads((ROOT / 'windows-app/release-inputs.json').read_text())['version']
    build = int((ROOT / 'BUILD').read_text(encoding='ascii').strip()) if args.build_qualified else None
    if build is not None and build < 1:
        raise ValueError('BUILD must be positive')
    prefix = f'VideoDescriptor-{version}' + (f'-build.{build}' if build is not None else '') + '-windows-x64'
    expected = {prefix + '.zip', prefix + '-setup.exe'}
    assert {entry['file'] for entry in entries} == expected, 'Release must supply ZIP and installer checksums'
    if {p.name for suffix in ('*.zip', '*.exe') for p in directory.glob(suffix)} != expected:
        raise ValueError('Publication directory contains extra or missing distributables')
    for entry in entries:
        path = directory / entry['file']
        assert path.name == entry['file'], 'Unsafe asset path'
        with path.open('rb') as source:
            assert hashlib.file_digest(source, 'sha256').hexdigest() == entry['sha256'], path.name
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    with zipfile.ZipFile(directory / (prefix + '.zip')) as archive:
        manifest = check_public_zip(archive)
    if (ROOT / 'BUILD').is_file():
        assert manifest.get('build') == int((ROOT / 'BUILD').read_text(encoding='ascii').strip()), 'Release build differs from the repository BUILD file'
    provenance_path = directory / 'acceptance-provenance.json'
    if args.record:
        provenance_path.write_text(json.dumps({'git_sha': revision, 'build': manifest.get('build'), 'artifacts': entries}, indent=2), encoding='utf-8')
    provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
    assert provenance['git_sha'] == revision, 'Release artifact does not belong to the checked-out tag revision'
    assert provenance['artifacts'] == entries, 'Release hashes differ from accepted artifacts'
    assert provenance.get('build') == manifest.get('build'), 'Release build differs from accepted build identity'
    assert manifest['version'] == version
    print('PASS: exact artifact checksums and source revision', revision)


if __name__ == '__main__':
    main()
