import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def modules(monkeypatch):
    source = Path(__file__).resolve().parents[1] / 'windows-app'
    monkeypatch.syspath_prepend(str(source))
    result = []
    for name in ('component_cache', 'build_cached'):
        spec = importlib.util.spec_from_file_location(name, source / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result.append(module)
    return result


def manifest(root):
    payload = b'python fixture'
    python = root / 'python/python.exe'
    python.parent.mkdir(parents=True)
    python.write_bytes(payload)
    model = root / 'windows-app/domestic/whisper/model.bin'
    model.parent.mkdir(parents=True)
    model.write_bytes(b'model')
    result = {'version': '1.0.0', 'profile': 'domestic', 'python_source': {'sha256': 'python'},
              'vcrt_source': {'sha256': 'vcrt'}, 'wheels': [],
              'domestic': {'whisper_revision': 'speech', 'diarization_revision': 'speakers',
                           'wheels': [], 'webview_sha256': 'webview'},
              'files': [{'path': 'python/python.exe', 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()},
                        {'path': 'windows-app/domestic/whisper/model.bin', 'bytes': 5, 'sha256': 'model'},
                        {'path': 'windows-app/component-manifest.json', 'bytes': 2, 'sha256': 'manifest'}]}
    (root / 'release-manifest.json').write_text(json.dumps(result))
    here = root / 'windows-app'
    (here / 'config.local.json').write_text('{}')
    marker = here / 'runtime/domestic-setup.json'
    marker.parent.mkdir()
    marker.write_text(json.dumps({'root': str(root.resolve()), 'speech_checked': True, 'diarization_checked': True}))
    return result


def test_application_version_does_not_invalidate_component_archive(modules, tmp_path):
    component, _ = modules
    current = manifest(tmp_path)
    before = component.digest(component.runtime_contract(current))
    current['version'] = '1.0.1'
    current['files'].append({'path': 'video_descriptor/assets/app.js', 'sha256': 'new ui'})
    assert component.digest(component.runtime_contract(current)) == before
    current['python_source']['sha256'] = 'changed runtime'
    assert component.digest(component.runtime_contract(current)) != before


def test_model_proof_is_reused_for_ui_changes_and_invalidated_for_backend(modules, tmp_path):
    component, _ = modules
    current = manifest(tmp_path)
    current['component_cache_key'] = 'runtime'
    current['files'].append({'path': 'windows-app/whisper_worker.py', 'sha256': 'backend'})
    before = component.validation_key(current)
    current['files'].append({'path': 'video_descriptor/assets/app.js', 'sha256': 'ui'})
    assert component.validation_key(current) == before
    current['files'][-2]['sha256'] = 'new backend'
    assert component.validation_key(current) != before


def test_installer_reuses_compatible_complete_components_and_rejects_missing_files(modules, tmp_path):
    component, _ = modules
    required = manifest(tmp_path)
    required['component_cache_key'] = component.digest(component.runtime_contract(required))
    assert component.reusable_install(tmp_path, required)
    (tmp_path / 'windows-app/domestic/whisper/model.bin').unlink()
    assert not component.reusable_install(tmp_path, required)


def test_corrupt_python_is_not_reused_even_if_its_size_is_unchanged(modules, tmp_path):
    component, _ = modules
    required = manifest(tmp_path)
    required['component_cache_key'] = component.digest(component.runtime_contract(required))
    path = tmp_path / 'python/python.exe'
    path.write_bytes(b'x' * path.stat().st_size)
    assert not component.reusable_install(tmp_path, required)


def test_cache_hit_never_unpacks_seed_or_recompresses_dependencies(modules, tmp_path, monkeypatch):
    component, builder = modules
    inputs = {'pinned': 'inputs'}
    key = component.digest(inputs)
    directory = tmp_path / 'component-bundles' / key
    directory.mkdir(parents=True)
    (directory / 'components.zip').write_bytes(b'already compressed archive')
    record = {'key': key, 'archive_sha256': builder.sha256(directory / 'components.zip')}
    (directory / 'cache.json').write_text(json.dumps(record))
    monkeypatch.setattr(builder, 'expected_contract', lambda: inputs)
    unzip = Mock(side_effect=AssertionError('Cache hit must not unpack or recompress'))
    monkeypatch.setattr(builder.zipfile, 'ZipFile', unzip)
    assert builder.cache_components(tmp_path, tmp_path / 'missing.zip', None) == (directory, record)
    unzip.assert_not_called()


def test_changed_runtime_requires_new_cache_key(modules):
    component, builder = modules
    first = builder.expected_contract()
    second = {**first, 'whisper_revision': first['whisper_revision'] + '-changed'}
    assert component.digest(first) != component.digest(second)


def test_bundled_model_does_not_probe_unrelated_external_npu_venv(modules, tmp_path, monkeypatch):
    from compute import ComputeManager
    here = tmp_path / 'installed/windows-app'
    python = here.parent / 'python/python.exe'
    python.parent.mkdir(parents=True)
    python.write_bytes(b'python')
    benchmark = tmp_path / 'external-benchmark'
    blocked = benchmark / '.venv-npu/Scripts/python.exe'
    is_file = Path.is_file

    def inspect(path):
        if path == blocked:
            raise OSError('untrusted mount point')
        return is_file(path)

    monkeypatch.setattr(Path, 'is_file', inspect)
    value = {'workspace': str(tmp_path / 'workspace'), 'npu_worker_directory': str(benchmark),
             'whisper_model_directory': str(here / 'domestic/whisper')}
    manager = ComputeManager(value, here)
    assert manager.backends['NPU']['command'][0] == str(python)
    assert '--device' in manager.backends['NPU']['command']


def test_corrupt_component_archive_is_rebuilt_from_verified_seed(modules, tmp_path, monkeypatch):
    import zipfile
    component, builder = modules
    source = tmp_path / 'source'
    source.mkdir()
    base = manifest(source)
    for entry in base['files']:
        path = source / entry['path']
        if path.is_file():
            entry['sha256'] = builder.sha256(path)
    contract = component.runtime_contract(base)
    monkeypatch.setattr(builder, 'expected_contract', lambda: contract)
    key = component.digest(contract)
    cache = tmp_path / 'cache'
    directory = cache / 'component-bundles' / key
    directory.mkdir(parents=True)
    (directory / 'components.zip').write_bytes(b'corrupt')
    (directory / 'cache.json').write_text(json.dumps({'key': key, 'archive_sha256': 'wrong'}))
    seed = tmp_path / 'seed.zip'
    with zipfile.ZipFile(seed, 'w') as archive:
        archive.writestr('release-manifest.json', json.dumps(base))
        for entry in base['files']:
            if entry['path'].startswith(component.PREFIXES):
                archive.write(source / entry['path'], entry['path'])
    result, record = builder.cache_components(cache, seed, None)
    assert result == directory
    assert builder.sha256(directory / 'components.zip') == record['archive_sha256']
    with zipfile.ZipFile(directory / 'components.zip') as archive:
        assert archive.read('windows-app/domestic/whisper/model.bin') == b'model'


def test_inconsistent_requirements_are_not_accepted_as_a_cache_hit(modules, tmp_path):
    _, builder = modules
    requirements = tmp_path / 'requirements.txt'
    requirements.write_text('example==2.0\n')
    with pytest.raises(ValueError, match='do not match'):
        builder.validate_lock(requirements, [{'file': 'example-1.0-py3-none-any.whl', 'sha256': 'hash'}])


def test_untrusted_seed_digest_is_rejected_before_unpacking(modules, tmp_path, monkeypatch):
    _, builder = modules
    monkeypatch.setattr(builder, 'expected_contract', lambda: {'pins': 'fixed'})
    seed = tmp_path / 'tampered.zip'
    seed.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='seed archive checksum mismatch'):
        builder.cache_components(tmp_path / 'cache', seed, None, '0' * 64)
