import hashlib
import json
import zipfile

import pytest

from scripts import ci_artifacts


def package(tmp_path, *, changes=None, payload=None, unlisted=None):
    payload = payload or {}
    manifest = {'profile': 'standard', 'domestic': None, 'whisper_weights_included': False,
                'files': [{'path': name} for name in payload], **(changes or {})}
    target = tmp_path / 'package.zip'
    with zipfile.ZipFile(target, 'w') as archive:
        archive.writestr('release-manifest.json', json.dumps(manifest))
        for name, value in {**payload, **(unlisted or {})}.items():
            archive.writestr(name, value)
    return target


def test_standard_package_is_accepted(tmp_path):
    with zipfile.ZipFile(package(tmp_path, payload={'video_descriptor/app.py': b'app'})) as archive:
        assert ci_artifacts.check_public_zip(archive)['profile'] == 'standard'


@pytest.mark.parametrize('same', [True, False])
def test_runtime_build_identity_must_match_manifest(tmp_path, same):
    info = 1
    payload = {'BUILD': '1\n' if same else '2\n'}
    with zipfile.ZipFile(package(tmp_path, changes={'build': info}, payload=payload)) as archive:
        if same:
            ci_artifacts.check_public_zip(archive)
        else:
            with pytest.raises(ValueError, match='build number'):
                ci_artifacts.check_public_zip(archive)


@pytest.mark.parametrize('name', ['ctranslate2/models/__init__.py',
                                 'onnxruntime/transformers/models/whisper/convert_to_onnx.py',
                                 'tokenizers/models/__init__.pyi'])
def test_dependency_source_modules_named_models_are_not_downloaded_weights(tmp_path, name):
    path = 'python/Lib/site-packages/' + name
    with zipfile.ZipFile(package(tmp_path, payload={path: b'# pinned dependency source'})) as archive:
        ci_artifacts.check_public_zip(archive)


@pytest.mark.parametrize('changes', [{'profile': 'domestic'}, {'profile': 'cached'}, {'profile': None},
                                     {'domestic': {}}, {'whisper_weights_included': True},
                                     {'whisper_weights_included': None}, {'component_cache_key': 'private-cache'}])
def test_private_or_unknown_profile_cannot_be_published(tmp_path, changes):
    with zipfile.ZipFile(package(tmp_path, changes=changes)) as archive, pytest.raises(ValueError, match='standard package'):
        ci_artifacts.check_public_zip(archive)


@pytest.mark.parametrize('name', ['windows-app/domestic/whisper/config.json', 'runtime/models/config.json',
                                 'renamed/model.bin', 'hidden/weights.safetensors', 'assets/network.onnx',
                                 'hidden/weights.GGUF', 'hidden/weights.pt', 'components.zip',
                                 'python/Lib/site-packages/ctranslate2/models/weights.bin',
                                 'python/Lib/site-packages/tokenizers/models/weights.onnx',
                                 'cache-reference.json', '.env.local', 'windows-app/config.local.json',
                                 'windows-app/domestic_setup.py', '../escaped/model.bin'])
def test_renaming_archive_does_not_hide_models_or_private_payload(tmp_path, name):
    with zipfile.ZipFile(package(tmp_path, payload={name: b'private'})) as archive, pytest.raises(ValueError, match='cannot be published'):
        ci_artifacts.check_public_zip(archive)


def test_actual_archive_entries_are_checked_even_when_manifest_omits_them(tmp_path):
    with zipfile.ZipFile(package(tmp_path, unlisted={'surprise.py': b'unknown'})) as archive, pytest.raises(ValueError, match='unlisted'):
        ci_artifacts.check_public_zip(archive)


def test_dependency_vad_requires_exact_reviewed_bytes_and_license(tmp_path, monkeypatch):
    name = 'python/Lib/site-packages/faster_whisper/assets/silero_vad_v6.onnx'
    monkeypatch.setattr(ci_artifacts, 'APPROVED_ONNX', {name: hashlib.sha256(b'reviewed').hexdigest()})
    for content, notice, reason in [(b'other', True, 'Unreviewed'), (b'reviewed', False, 'license notice')]:
        payload = {name: content}
        if notice:
            payload['windows-app/licenses/SILERO-VAD-LICENSE.txt'] = b'MIT license fixture'
        with zipfile.ZipFile(package(tmp_path, payload=payload)) as archive, pytest.raises(ValueError, match=reason):
            ci_artifacts.check_public_zip(archive)
    with zipfile.ZipFile(package(tmp_path, payload={name: b'reviewed',
                                                   'windows-app/licenses/SILERO-VAD-LICENSE.txt': b'MIT license fixture'})) as archive:
        ci_artifacts.check_public_zip(archive)


def test_publication_gate_runs_before_publishing_assets_and_registry_image():
    from pathlib import Path

    import yaml
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / '.github/workflows/container-release.yml').read_text(encoding='utf-8'))
    steps = workflow['jobs']['publish']['steps']
    gate = next(i for i, step in enumerate(steps) if 'ci_artifacts.py --directory accepted-windows' in step.get('run', ''))
    publish = [i for i, step in enumerate(steps) if any(command in step.get('run', '') for command in ['gh release create', 'docker push'])]
    assert publish and all(gate < index for index in publish)
    builder = (root / 'windows-app/build_release.py').read_text(encoding='utf-8')
    assert "['/DPublicRelease=1']" in builder
    installer = (root / 'windows-app/installer.iss').read_text(encoding='utf-8')
    assert '#error PublicRelease cannot include Domestic or CachedComponents payloads' in installer
