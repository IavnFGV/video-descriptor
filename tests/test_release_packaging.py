import importlib.util
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest


def builder():
    path = Path(__file__).resolve().parents[1] / 'windows-app/build_release.py'
    spec = importlib.util.spec_from_file_location('build_release', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('same_directory', [True, False])
def test_packaged_smoke_checks_workspace_identity_not_path_spelling(tmp_path, monkeypatch, same_directory):
    path = Path(__file__).resolve().parents[1] / 'windows-app/verify_release.py'
    spec = importlib.util.spec_from_file_location('verify_release', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    folder = tmp_path / 'portable'
    expected = folder / 'windows-app/runtime/workspace'
    expected.mkdir(parents=True)
    other = tmp_path / 'foreign'
    other.mkdir()
    # Distinct spelling for the same real directory, analogous to a Windows 8.3 alias.
    reported = expected / '..' / 'workspace' if same_directory else other
    monkeypatch.setenv('SystemRoot', str(tmp_path))
    monkeypatch.setattr(module.subprocess, 'Popen', Mock())
    monkeypatch.setattr(module, 'request', lambda *args: {
        'app': 'video-descriptor-windows', 'workspace': str(reported), 'instance': 'test'})
    if same_directory:
        _, log, instance = module.start(folder, 12345)
        log.close()
        assert instance == 'test'
    else:
        with pytest.raises(AssertionError):
            module.start(folder, 12345)


def test_release_zip_is_byte_reproducible_and_independent_of_mtime(tmp_path):
    module = builder()
    folder = tmp_path / 'payload'
    folder.mkdir()
    source = folder / 'app.py'
    source.write_text('print("test")')
    first, second = tmp_path / 'first.zip', tmp_path / 'second.zip'
    module.deterministic_zip(folder, first)
    import os
    os.utime(source, (1800000000, 1800000000))
    module.deterministic_zip(folder, second)
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize('name', ['../secret', '/absolute', 'C:/escape', 'dir\\escape'])
def test_release_rejects_unsafe_archive_names(name):
    with pytest.raises(ValueError, match='Unsafe'):
        builder().safe_member(name)


def test_release_input_checksum_failure_never_uses_bad_cached_bytes(tmp_path):
    module = builder()
    (tmp_path / 'python.zip').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='checksum'):
        module.download({'url': 'https://example.invalid/python.zip', 'sha256': '0' * 64}, tmp_path)


def test_release_source_allowlist_excludes_user_data_models_and_secrets():
    module = builder()
    paths = [p.relative_to(module.ROOT) for p in module.source_paths()]
    assert Path('video_descriptor/speech.py') in paths
    assert Path('windows-app/config.example.json') in paths
    for path in paths:
        assert not {'runtime', 'data', 'output', '.git', '__pycache__'}.intersection(path.parts)
        assert not path.name.startswith('.env') and path.name != 'config.local.json'


def test_wheel_collision_is_an_error_instead_of_silent_overwrite(tmp_path):
    module = builder()
    wheels = []
    for index in range(2):
        path = tmp_path / f'{index}.whl'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('package/shared.py', str(index))
        wheels.append(path)
    with pytest.raises(ValueError, match='Conflicting'):
        module.unpack_wheels(wheels, tmp_path / 'libraries')


def test_wheel_resolution_ignores_stale_unrelated_cache_entries(tmp_path):
    module = builder()
    requirements = tmp_path / 'requirements.txt'
    requirements.write_text('example==2.0\n')
    for name, version in [('example', '1.0'), ('example', '2.0'), ('unrelated', '1.0')]:
        with zipfile.ZipFile(tmp_path / f'{name}-{version}.whl', 'w') as archive:
            archive.writestr(f'{name}-{version}.dist-info/METADATA', f'Name: {name}\nVersion: {version}\n')
    assert [p.name for p in module.resolved_wheels(tmp_path, requirements)] == ['example-2.0.whl']


def test_lifecycle_guard_matches_own_install_without_resolving_foreign_paths(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'windows-app/release_lifecycle.py'
    spec = importlib.util.spec_from_file_location('release_lifecycle', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / 'installation'
    root.mkdir()
    processes = [Mock(pid=2, info={'exe': str(root / 'python/python.exe'), 'cmdline': []}),
                 Mock(pid=3, info={'exe': None, 'cmdline': [r'\\unavailable-host\share\file.py']})]
    monkeypatch.setattr(module.psutil, 'process_iter', lambda attrs: processes)
    monkeypatch.setattr(module.psutil, 'Process', lambda: Mock(pid=1, parents=list))
    original = Path.resolve

    def local_only(value, *args, **kwargs):
        assert 'unavailable-host' not in str(value)
        return original(value, *args, **kwargs)

    monkeypatch.setattr(Path, 'resolve', local_only)
    assert module.busy(root) == [2]
