import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def module(name, monkeypatch):
    folder = Path(__file__).resolve().parents[1] / 'windows-app'
    monkeypatch.syspath_prepend(str(folder))
    spec = importlib.util.spec_from_file_location(name, folder / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.mark.parametrize('git_blob', [False, True])
def test_model_bundle_copies_only_pinned_verified_files(tmp_path, monkeypatch, git_blob):
    bundle = module('domestic_bundle', monkeypatch)
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.mkdir()
    (source / 'weights.bin').write_bytes(b'weights')
    (source / 'hf-token').write_text('private')
    item = {'name': 'weights.bin', 'bytes': 7}
    item.update({'git_blob': hashlib.sha1(b'blob 7\0weights').hexdigest()} if git_blob else
                {'sha256': hashlib.sha256(b'weights').hexdigest()})
    bundle.copy_model(source, target, {'files': [item]})
    assert [p.name for p in target.iterdir()] == ['weights.bin']
    (source / 'weights.bin').write_bytes(b'changed')
    with pytest.raises(ValueError, match='checksum'):
        bundle.copy_model(source, target, {'files': [item]})


def test_domestic_defaults_preserve_explicit_devices_and_external_models(tmp_path, monkeypatch):
    setup = module('domestic_setup', monkeypatch)
    existing = {'diarization_python': 'external/python.exe', 'diarization_model_directory': 'external/model',
                'diarization_device': 'xpu', 'diarization_requested_device': 'xpu',
                'whisper_model_directory': 'external/whisper', 'records_directory': 'my-records'}
    assert setup.defaults(tmp_path, existing) == existing
    initial = setup.defaults(tmp_path, {})
    assert initial['diarization_requested_device'] == 'cpu'
    assert Path(initial['diarization_python']).is_relative_to(tmp_path)
    assert 'records_directory' not in initial


def test_cpu_wheel_lock_covers_pins_including_local_build_versions(monkeypatch):
    build = module('build_release', monkeypatch)
    lock = json.loads((build.HERE / 'domestic-wheels.json').read_text())
    pins = [line for line in (build.HERE / 'requirements-pyannote-cpu.lock').read_text().splitlines()
            if line and not line.startswith(('#', '--'))]
    assert len(lock) == len(pins)
    assert len({entry['file'] for entry in lock}) == len(pins)
    assert any(entry['file'].startswith('torch-') and '+cpu-' in entry['file'] for entry in lock)
    assert all(len(entry['sha256']) == 64 for entry in lock)


def test_hook_uses_default_cached_full_profile_without_starting_a_build(tmp_path, monkeypatch):
    folder = Path(__file__).resolve().parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(folder))
    import local_build
    monkeypatch.setattr(local_build, 'git', lambda *args: str(tmp_path))
    hook = local_build.install_hook(tmp_path)
    assert '-Background' in hook.read_text()
    assert '-Domestic' not in hook.read_text()
    assert not (tmp_path / 'queue').exists()
