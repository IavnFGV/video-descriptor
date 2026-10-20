"""Offline manager contracts: interruption, consent, rollback and real proof gates."""
import importlib
import json
import sys
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows-app'))
cm = importlib.import_module('component_manager')


@pytest.fixture
def manager(tmp_path):
    here = tmp_path / 'Приложение с пробелами'
    here.mkdir()
    (here / 'component-manifest.json').write_text('{}')
    backend = SimpleNamespace(_lock=threading.RLock(), operation=None, model=tmp_path / 'model',
                              value={}, here=here)
    setup = SimpleNamespace(manager=backend, here=here, guard=lambda: None)
    return cm.ComponentManager(setup, tmp_path / 'Данные AI')


def wait(manager):
    for _ in range(200):
        if not manager.active:
            return
        time.sleep(.01)
    raise AssertionError('operation did not finish')


@pytest.mark.parametrize('action', ['install', 'pull', 'remove'])
def test_explicit_consent(manager, action):
    with pytest.raises(ValueError, match='Подтвердите'):
        manager.action('ollama', {'action': action})
    assert manager.active is None


def test_managed_python_uses_verified_app_local_crt(manager):
    source = manager.here.parent / 'python'
    source.mkdir()
    library = source / 'msvcp140.dll'
    library.write_bytes(b'reviewed-runtime-fixture')
    profile = {'vcrt': {'files': [{'name': library.name, 'sha256': cm.checksum(library)}]}}
    (manager.here / 'release-inputs.json').write_text(json.dumps(profile))
    destination = manager.root / 'candidate/Scripts'
    destination.mkdir(parents=True)
    manager.stage_python_runtime_libraries(destination)
    assert (destination / library.name).read_bytes() == library.read_bytes()
    library.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='повреждены'):
        manager.stage_python_runtime_libraries(destination)
    assert (destination / library.name).read_bytes() == b'reviewed-runtime-fixture'


def test_owned_environment_size_and_removal_support_long_windows_paths(manager, monkeypatch):
    folder = manager.root / 'candidate'
    directory = cm.native_path(folder / ('a' * 100) / ('b' * 100))
    directory.mkdir(parents=True)
    payload = directory / 'fixture.txt'
    payload.write_bytes(b'long-path-payload')
    marker = folder / '.managed.json'
    cm.atomic(marker, {'component': 'diarization'})
    assert manager.size(folder) == len(b'long-path-payload') + marker.stat().st_size
    manager.components['diarization']['path'] = str(folder)
    monkeypatch.setattr(manager, 'publish', lambda changes: None)
    manager.remove('diarization')
    assert not folder.exists()


def test_restart_recovers_incomplete_operation(manager):
    manager.update('diarization', 'installing', message='pending')
    restored = cm.ComponentManager(manager.setup, manager.root)
    assert restored.components['diarization']['state'] == 'error'
    assert 'перезапуском' in restored.components['diarization']['message']


def test_no_ready_on_failure_and_old_proof_survives(manager, monkeypatch):
    manager.update('ollama', 'ready', proof={'previous_working': True})
    monkeypatch.setattr(manager, 'ollama', lambda *a: (_ for _ in ()).throw(ValueError('failed probe')))
    manager.action('ollama', {'action': 'check'})
    wait(manager)
    assert manager.components['ollama']['state'] == 'error'
    assert manager.components['ollama']['proof']['previous_working']
    assert manager.manager.operation is None


def test_cancellation_and_parallel_guard(manager, monkeypatch):
    def operation(*args):
        manager.cancel.wait(5)
        manager.check_cancel()
    monkeypatch.setattr(manager, 'ollama', operation)
    manager.action('ollama', {'action': 'check'})
    with pytest.raises(RuntimeError):
        manager.action('diarization', {'action': 'check'})
    manager.action('ollama', {'action': 'cancel'})
    wait(manager)
    assert manager.components['ollama']['state'] == 'error'
    assert 'Остановлено' in manager.components['ollama']['message']


def test_ready_requires_operation_proof_and_persists(manager, monkeypatch):
    monkeypatch.setattr(manager, 'ollama', lambda *a: {'generation_checked': True})
    manager.action('ollama', {'action': 'check'})
    wait(manager)
    saved = json.loads(manager.path.read_text(encoding='utf-8'))
    assert saved['ollama']['state'] == 'ready'
    assert saved['ollama']['proof']['generation_checked']


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'C:/root', 'dir\\file'])
def test_archive_traversal_rejected(manager, name):
    with pytest.raises(ValueError):
        cm.safe_member(name)
    if '\\' in name:
        return  # zipfile normalizes separators on Windows before extraction.
    archive = manager.root / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as stream:
        stream.writestr(name, b'bad')
    with pytest.raises(ValueError):
        cm.extract(archive, manager.root / 'stage', threading.Event())


def test_never_remove_external_environment(manager):
    manager.update('diarization', path=str(manager.here))
    with pytest.raises(ValueError, match='только компонент'):
        manager.remove('diarization')
    assert manager.here.exists()


def test_model_integrity_checks_git_blob_and_lfs(manager, tmp_path):
    import hashlib
    data = b'configuration'
    path = tmp_path / 'config.yaml'
    path.write_bytes(data)
    item = {'bytes': len(data), 'git_blob': hashlib.sha1(b'blob 13\0' + data).hexdigest()}
    assert manager.verify_file(path, item)
    item = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    assert manager.verify_file(path, item)
    path.write_bytes(b'bad')
    assert not manager.verify_file(path, item)


def test_explicit_xpu_never_falls_back(manager, monkeypatch, tmp_path):
    model = tmp_path / 'model'
    model.mkdir()
    (model / 'config.yaml').write_text('test')
    manager.manager.value['diarization_model_directory'] = str(model)
    calls = []
    def probe(device, *a, **kw):
        calls.append(device)
        raise ValueError('XPU inference failed')
    monkeypatch.setattr(manager, 'diarization_runtime', probe)
    with pytest.raises(ValueError, match='XPU inference'):
        manager.diarization({'device': 'xpu'}, 'check')
    assert calls == ['xpu']


def test_auto_fallback_is_probed_and_explained(manager, monkeypatch, tmp_path):
    ds = importlib.import_module('diarization_setup')
    monkeypatch.setattr(ds, 'detect_adapters', lambda: ['Intel Arc 140V'])
    model = tmp_path / 'model'
    model.mkdir()
    (model / 'config.yaml').write_text('test')
    manager.manager.value['diarization_model_directory'] = str(model)
    calls = []
    def probe(device, *a, **kw):
        calls.append(device)
        if device == 'xpu':
            raise ValueError('GPU failed')
        return tmp_path / 'Scripts/python.exe', {'device': 'cpu', 'turns': [{'speaker': 'S1'}]}
    monkeypatch.setattr(manager, 'diarization_runtime', probe)
    manager.diarization({'device': 'auto'}, 'check')
    assert calls == ['xpu', 'cpu']
    assert manager.manager.value['diarization_device'] == 'cpu'
    assert 'GPU failed' in manager.components['diarization']['fallback_reason']


def test_gated_model_message_does_not_expose_token(manager, monkeypatch):
    manager.manifest['diarization_model'] = {'revision': 'a' * 40, 'source': 'https://huggingface.co/pyannote/test',
                                               'files': [{'name': 'config.yaml', 'bytes': 3}]}
    class Response:
        status_code = 403
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(cm.requests.Session, 'get', lambda *a, **kw: Response())
    with pytest.raises(ValueError, match='разрешение Hugging Face') as error:
        manager.hf_model('hf_NEVER_LOG_THIS')
    assert 'NEVER_LOG' not in str(error.value)


def test_download_is_not_repeated_for_verified_cache(manager, monkeypatch):
    import hashlib
    data = b'verified'
    profile = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    folder = manager.root / 'downloads'
    folder.mkdir()
    (folder / profile['sha256']).write_bytes(data)
    monkeypatch.setattr(cm.requests.Session, 'get', lambda *a, **kw: pytest.fail('network called'))
    assert manager.download(profile, 'ollama').read_bytes() == data



def test_other_instance_does_not_recover_a_live_operation(manager, monkeypatch):
    def operation(*args):
        manager.cancel.wait(5)
        manager.check_cancel()
    monkeypatch.setattr(manager, 'ollama', operation)
    manager.action('ollama', {'action': 'check'})
    second = cm.ComponentManager(manager.setup, manager.root)
    assert second.snapshot()['active'] == 'ollama'
    assert second.components['ollama']['state'] == 'verifying'
    with pytest.raises(RuntimeError, match='другом экземпляре'):
        second.action('diarization', {'action': 'check'})
    manager.action('ollama', {'action': 'cancel'})
    wait(manager)
    assert second.snapshot()['active'] is None


def test_startup_keeps_proof_without_claiming_live_readiness(manager):
    manager.update('whisper', 'ready', proof={'segments': 3})
    restarted = cm.ComponentManager(manager.setup, manager.root)
    assert restarted.components['whisper']['state'] == 'installed'
    assert restarted.components['whisper']['proof']['segments'] == 3


def test_managed_version_update_detection(manager):
    manager.manifest['ollama'] = {'version': '2.0'}
    manager.manager.value['ollama_mode'] = 'managed'
    manager.update('ollama', 'installed', version='1.0', path=str(manager.root / 'ollama-1.0'))
    row = next(row for row in manager.snapshot()['components'] if row['id'] == 'ollama')
    assert row['state'] == 'update_available'


def test_corrupt_state_schema_does_not_break_startup(manager):
    manager.path.write_text('[]')
    restored = cm.ComponentManager(manager.setup, manager.root)
    assert all(row['state'] in {'not_installed', 'installed'} for row in restored.snapshot()['components'])



def test_inbox_shell_environment_does_not_inherit_pwsh_modules(monkeypatch):
    from video_descriptor.platform_support import windows_powershell, windows_shell_environment
    monkeypatch.setenv('PSModulePath', 'incompatible PowerShell 7 modules')
    monkeypatch.setenv('PATH', 'no shell executables')
    environment = windows_shell_environment({'VD_SIGNATURE_FILE': 'example'})
    assert not any(key.upper() == 'PSMODULEPATH' for key in environment)
    assert environment['VD_SIGNATURE_FILE'] == 'example'
    assert windows_powershell().endswith('System32\\WindowsPowerShell\\v1.0\\powershell.exe') if sys.platform == 'win32' else windows_powershell().endswith('powershell.exe')



def test_ollama_api_alone_does_not_claim_language_model_ready(manager, monkeypatch):
    monkeypatch.setattr(manager, 'ollama', lambda *a: {'api_version': {'version': '1'}, 'generation_checked': False})
    manager.action('ollama', {'action': 'check'})
    wait(manager)
    assert manager.components['ollama']['state'] == 'installed'
    assert 'Выберите модель' in manager.components['ollama']['message']


def test_single_local_ai_preparation_requires_consent_and_managed_mode(manager):
    with pytest.raises(ValueError, match='Подтвердите'):
        manager.action('ollama', {'action': 'prepare', 'model': 'example'})
    with pytest.raises(ValueError, match='управляемую'):
        manager.action('ollama', {'action': 'prepare', 'model': 'example', 'confirmed': True})
    assert manager.active is None


def test_pending_action_rejects_wrong_component_before_start(manager):
    manager.manager.value['workspace'] = str(manager.here)
    with pytest.raises(ValueError, match='соответствует'):
        manager.action('diarization', {'action': 'check', 'resume': {'task': 'translate', 'folder': 'record'}})
    assert manager.active is None
    assert manager.manager.operation is None


def test_failed_preparation_keeps_resume_target_and_retry_enqueues_once(manager, monkeypatch):
    import video_descriptor.diarization_postprocess as diarization
    from video_descriptor import construction, jobs
    manager.manager.value['workspace'] = str(manager.here)
    monkeypatch.setattr(construction, 'checked_folder', lambda root, folder: root / folder)
    enqueued = []
    monkeypatch.setattr(jobs, 'start_worker', lambda root: None)
    monkeypatch.setattr(diarization, 'enqueue', lambda root, folder, value: (enqueued.append(folder) or {'id': 'resumed'}))
    monkeypatch.setattr(manager, 'diarization', lambda body, action: (_ for _ in ()).throw(ValueError('retry')))
    manager.action('diarization', {'action': 'check', 'resume': {'folder': 'source-record', 'task': 'diarize'}})
    wait(manager)
    assert enqueued == []
    assert manager.components['diarization']['pending_action']['folder'] == 'source-record'
    monkeypatch.setattr(manager, 'diarization', lambda body, action: {'turns': [1]})
    manager.action('diarization', {'action': 'check'})
    wait(manager)
    assert enqueued == ['source-record']
    assert manager.components['diarization']['resumed_job'] == 'resumed'
    assert manager.components['diarization']['pending_action'] is None


def test_resume_never_crosses_workspaces(manager, monkeypatch):
    manager.manager.value['workspace'] = str(manager.here)
    manager.components['diarization']['pending_action'] = {'workspace': 'another-workspace', 'folder': 'record', 'task': 'diarize'}
    monkeypatch.setattr(manager, 'diarization', lambda body, action: {})
    manager.action('diarization', {'action': 'check'})
    wait(manager)
    assert manager.components['diarization']['state'] == 'ready'
    assert manager.components['diarization']['pending_action'] is None
