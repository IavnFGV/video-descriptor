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


def test_cabinet_extraction_uses_inbox_expand_even_with_git_path_first(tmp_path, monkeypatch):
    module = builder()
    windows = tmp_path / 'Windows'
    monkeypatch.setenv('SystemRoot', str(windows))
    monkeypatch.setenv('PATH', str(tmp_path / 'Git/usr/bin'))
    run = Mock(return_value=Mock(returncode=0, stdout=b'', stderr=b''))
    monkeypatch.setattr(module.subprocess, 'run', run)
    module.expand_cabinet(tmp_path / 'input.cab', tmp_path / 'out')
    assert run.call_args.args[0][0] == str(windows / 'System32/expand.exe')
    assert run.call_args.args[0][1] == '-F:*'


def test_cabinet_failure_includes_real_tool_diagnostic(tmp_path, monkeypatch):
    module = builder()
    monkeypatch.setattr(module.subprocess, 'run', Mock(return_value=Mock(
        returncode=1, stdout=b'', stderr=b'Cabinet file could not be opened')))
    with pytest.raises(RuntimeError, match='Cabinet file could not be opened'):
        module.expand_cabinet(tmp_path / 'bad.cab', tmp_path / 'out')


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


def test_zip_from_verified_wheel_inputs_matches_payload_bytes(tmp_path):
    module = builder()
    wheel = tmp_path / 'test.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('package/__init__.py', 'value = 42\n')
    folder = tmp_path / 'payload'
    cached = {}
    module.unpack_wheels([wheel], folder, cached)
    first, second = tmp_path / 'first.zip', tmp_path / 'second.zip'
    module.deterministic_zip(folder, first)
    module.deterministic_zip(folder, second, cached)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('package/__init__.py', 'tampered')
    with pytest.raises(ValueError, match='Archive changed'):
        module.deterministic_zip(folder, second, cached)


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


def lifecycle_module():
    path = Path(__file__).resolve().parents[1] / 'windows-app/release_lifecycle.py'
    spec = importlib.util.spec_from_file_location('lifecycle_stop', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('changed', ['pid_reused', 'foreign_executable', 'foreign_entry', 'wrong_root'])
def test_confirmed_stop_preflights_all_identities_before_terminating_any(tmp_path, monkeypatch, changed):
    module = lifecycle_module()
    root = tmp_path.resolve()
    first = Mock(pid=2)
    first.exe.return_value = str(root / 'python/python.exe')
    first.create_time.return_value = 10
    second = Mock(pid=3)
    second.exe.return_value = str(root / 'python/python.exe')
    second.create_time.return_value = 20
    entries = [{'pid': p.pid, 'exe': p.exe(), 'created': p.create_time(), 'owned': True}
               for p in (first, second)]
    recorded = {'root': str(root), 'processes': entries}
    if changed == 'pid_reused':
        second.create_time.return_value = 21
    elif changed == 'foreign_executable':
        second.exe.return_value = str(root.parent / 'foreign/python.exe')
    elif changed == 'foreign_entry':
        entries[1]['owned'] = False
    else:
        recorded['root'] = str(root.parent)
    current = Mock(pid=1, parents=list)
    monkeypatch.setattr(module.psutil, 'Process', lambda pid=None: {2:first, 3:second}.get(pid, current))
    with pytest.raises(ValueError):
        module.stop_confirmed(root, recorded)
    first.terminate.assert_not_called()
    second.terminate.assert_not_called()


def test_confirmed_stop_waits_and_rechecks_new_blockers(tmp_path, monkeypatch):
    module = lifecycle_module()
    root = tmp_path.resolve()
    worker = Mock(pid=2)
    worker.exe.return_value = str(root / 'python/python.exe')
    worker.create_time.return_value = 10
    current = Mock(pid=1, parents=list)
    monkeypatch.setattr(module.psutil, 'Process', lambda pid=None: worker if pid == 2 else current)
    monkeypatch.setattr(module.psutil, 'wait_procs', lambda processes, timeout: (processes, []))
    monkeypatch.setattr(module, 'busy', lambda root: [3])
    recorded = {'root': str(root), 'processes': [
        {'pid':2, 'created':10, 'exe':worker.exe(), 'owned':True}]}
    assert not module.stop_confirmed(root, recorded)
    worker.terminate.assert_called_once()


def test_installer_uses_new_helper_and_requires_interactive_consent():
    source = (Path(__file__).resolve().parents[1] / 'windows-app/installer.iss').read_text(encoding='utf-8')
    prepare = source.split('function PrepareInstallationProcesses()', 1)[1].split('function PrepareToInstall', 1)[0]
    assert "ExtractTemporaryFile('VD-release-lifecycle.py')" in prepare
    assert prepare.index('if WizardSilent then exit') < prepare.index('MsgBox(')
    assert prepare.index('<> IDYES then exit') < prepare.index("Arguments + ' --stop-confirmed'")
    assert 'MB_DEFBUTTON2' in prepare


def test_zip_verification_reports_real_file_counts_and_hash_completion(tmp_path, capsys):
    import hashlib
    import json
    path = Path(__file__).resolve().parents[1] / 'windows-app/verify_release.py'
    spec = importlib.util.spec_from_file_location('verify_progress', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    archive_path = tmp_path / 'test.zip'
    payload = b'fixture'
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('app/file.txt', payload)
    folder = tmp_path / 'unpacked'
    with zipfile.ZipFile(archive_path) as archive:
        module.extract_zip(archive, folder)
    (folder / 'release-manifest.json').write_text(json.dumps({'files': [
        {'path': 'app/file.txt', 'sha256': hashlib.sha256(payload).hexdigest()}]}))
    assert module.manifest_check(folder) == 1
    output = capsys.readouterr().out
    assert 'Распаковано 1/1 файлов' in output
    assert 'SHA256 совпадает: 1/1 файлов' in output
    (folder / 'app/file.txt').write_bytes(b'corrupted')
    with pytest.raises(AssertionError):
        module.manifest_check(folder)
    assert 'SHA256 совпадает' not in capsys.readouterr().out
