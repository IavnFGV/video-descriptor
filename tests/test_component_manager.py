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


def test_package_progress_reports_real_file_bytes_without_raw_output():
    metadata = cm.package_progress('Downloading torch-2.14.1+xpu-cp312-cp312-win_amd64.whl (1.5 GB)')
    assert metadata['package'] == 'torch'
    assert cm.package_progress('Progress 1048576 of 2097152', 'torch')['bytes'] == 1048576
    assert cm.package_progress('Progress 1048576 of 2097152', 'torch')['progress_scope'] == 'file'
    for raw in ['Progress 8 of 0', 'Progress 20 of 10', 'Downloading https://hf_secret@example.org/token.whl', 'ERROR: hf_secret']:
        assert cm.package_progress(raw) is None
    assert 'hf_secret' not in json.dumps(cm.package_progress('Collecting torch==2.14 (from https://hf_secret@example.org)'))


def test_model_progress_uses_only_known_stages_and_finite_counters():
    progress = cm.model_progress({'stage': 'embeddings', 'completed': 1, 'total': 4, 'message': 'hf_secret'})
    assert progress['total'] == 4 and progress['bytes'] == 1
    assert 'hf_secret' not in json.dumps(progress)
    assert cm.model_progress({'stage': 'unknown', 'message': 'secret'}) is None
    assert cm.model_progress({'stage': 'embeddings', 'completed': float('nan'), 'total': 4})['total'] == 0


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


def test_real_child_streams_progress_but_never_persists_raw_output(manager, monkeypatch):
    updates = []
    original = manager.update
    def update(key, state=None, **fields):
        updates.append((state, fields.copy()))
        original(key, state, **fields)
    monkeypatch.setattr(manager, 'update', update)
    script = ("import time; print('Downloading torch-2.14.1-py3-none-any.whl',flush=True); "
              "print('Progress 1024 of 2048',flush=True); time.sleep(.8); "
              "print('Installing collected packages: torch',flush=True); time.sleep(.8); "
              "print('ERROR: https://hf_secret@example.org/private',flush=True)")
    manager.run([sys.executable, '-u', '-c', script, 'pip', 'install'], 'diarization')
    assert any(state == 'downloading' and fields.get('bytes') == 1024 for state, fields in updates)
    assert any(fields.get('message') == 'Распаковываем и устанавливаем скачанные пакеты' for _, fields in updates)
    assert manager.components['diarization']['activity_at'] >= manager.components['diarization']['step_started_at']
    assert not manager.components['diarization']['process_running']
    assert 'hf_secret' not in manager.path.read_text()


def test_silent_child_can_be_cancelled_without_blocking_pipe_reader(manager):
    failures = []
    def run():
        try:
            manager.run([sys.executable, '-c', 'import time; time.sleep(20)'], 'diarization')
        except RuntimeError as exc:
            failures.append(str(exc))
    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 3
    while manager.process is None and time.monotonic() < deadline:
        time.sleep(.01)
    assert manager.process is not None
    owned_child = manager.process
    manager.cancel.set()
    thread.join(timeout=4)
    assert not thread.is_alive() and owned_child.poll() is not None
    assert failures and not manager.components['diarization']['process_running']


def test_real_child_reads_structured_model_progress_without_trusting_messages(manager, tmp_path):
    progress_file = tmp_path / 'progress.json'
    script = ("import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text("
              "'{\"stage\":\"embeddings\",\"completed\":1,\"total\":2,\"message\":\"hf_secret\"}'); time.sleep(.8)")
    manager.run([sys.executable, '-c', script, str(progress_file)], 'diarization', progress_file=progress_file)
    assert manager.components['diarization']['total'] == 2
    assert 'сравниваем голоса' in manager.components['diarization']['message']
    assert 'hf_secret' not in manager.path.read_text()


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


def test_gpu_check_does_not_probe_saved_cpu_environment(manager, monkeypatch):
    manager.manager.value.update(diarization_device='cpu', diarization_python='cpu/Scripts/python.exe')
    calls = []
    monkeypatch.setattr(manager, 'run', lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match='требуется отдельное окружение'):
        manager.diarization_runtime('xpu', manager.root, install=False)
    assert calls == []


def test_npu_diarization_rejected_before_start(manager):
    with pytest.raises(ValueError, match='для этой задачи не поддерживается'):
        manager.action('diarization', {'action': 'check', 'device': 'npu'})
    assert manager.active is None


def wait_plan(manager):
    for _ in range(300):
        if manager.plan.get('state') != 'running':
            return
        time.sleep(.01)
    raise AssertionError('preparation plan did not finish')


@pytest.mark.parametrize('body', [
    {'features': []},
    {'features': ['whisper']},
    {'features': ['diarization'], 'confirmed': True},
    {'features': ['ollama'], 'confirmed': True},
    {'features': ['whisper', 'whisper'], 'confirmed': True},
])
def test_preparation_validates_all_consents_before_start(manager, body):
    with pytest.raises(ValueError):
        manager.action(None, {'action': 'prepare_selected', **body})
    assert manager.active is None
    assert not manager.plan_path.exists()


def test_preparation_runs_selected_components_in_order_without_saving_token(manager, monkeypatch):
    manager.manager.value['workspace'] = str(manager.root / 'workspace')
    calls = []
    monkeypatch.setattr(manager, 'token', lambda token: calls.append('token-protected'))
    monkeypatch.setattr(manager, 'whisper', lambda action: calls.append('whisper') or {'verified': True})
    monkeypatch.setattr(manager, 'diarization', lambda body, action: calls.append('diarization') or {'verified': True})
    monkeypatch.setattr(manager, 'ollama', lambda body, action: calls.append('ollama') or {'generation_checked': True})
    manager.action(None, {'action': 'prepare_selected', 'features': ['ollama', 'diarization', 'whisper'],
                          'device': 'cpu', 'model': 'test-model', 'confirmed': True,
                          'hf_consent': True, 'token': 'hf_fixture-secret'})
    wait_plan(manager)
    assert manager.plan['state'] == 'ready'
    assert calls == ['token-protected', 'whisper', 'diarization', 'ollama']
    assert manager.plan['completed'] == ['whisper', 'diarization', 'ollama']
    assert 'hf_fixture-secret' not in manager.plan_path.read_text()


def test_preparation_stops_on_failure_and_keeps_completed_components(manager, monkeypatch):
    manager.manager.value['workspace'] = str(manager.root / 'workspace')
    monkeypatch.setattr(manager, 'whisper', lambda action: {'verified': True})
    monkeypatch.setattr(manager, 'diarization', lambda *args: (_ for _ in ()).throw(ValueError('GPU unavailable')))
    monkeypatch.setattr(manager, 'ollama', lambda *args: pytest.fail('Must not start after failed component'))
    manager.prepare_selected({'features': ['whisper', 'diarization', 'ollama'], 'device': 'cpu',
                              'model': 'test-model', 'confirmed': True, 'hf_consent': True})
    wait_plan(manager)
    assert manager.plan['state'] == 'error'
    assert manager.plan['completed'] == ['whisper']
    assert 'GPU unavailable' in manager.plan['message']
    assert manager.components['whisper']['state'] == 'ready'


def test_preparation_cancel_does_not_continue_queue_or_allow_parallel_action(manager, monkeypatch):
    manager.manager.value['workspace'] = str(manager.root / 'workspace')
    started = threading.Event()
    def probe(action):
        started.set()
        manager.cancel.wait(3)
        manager.check_cancel()
    monkeypatch.setattr(manager, 'whisper', probe)
    monkeypatch.setattr(manager, 'ollama', lambda *args: pytest.fail('Must not start after cancel'))
    manager.prepare_selected({'features': ['whisper', 'ollama'], 'model': 'test', 'confirmed': True})
    assert started.wait(2)
    with pytest.raises(RuntimeError, match='подготовка выбранных'):
        manager.action('ollama', {'action': 'check'})
    manager.action(None, {'action': 'cancel_selected'})
    wait_plan(manager)
    assert manager.plan['state'] == 'error'
    assert manager.plan['completed'] == []


def test_preparation_restart_reports_interruption_without_downloads(manager):
    cm.atomic(manager.plan_path, {'state': 'running', 'features': ['whisper'], 'completed': []})
    restored = cm.ComponentManager(manager.setup, manager.root)
    assert restored.plan['state'] == 'error'
    assert restored.active is None


def test_preparation_requires_missing_hf_token_before_any_download(manager):
    manager.manifest['diarization_model'] = {'revision': 'test-revision'}
    with pytest.raises(ValueError, match='токен чтения Hugging Face'):
        manager.prepare_selected({'features': ['whisper', 'diarization'], 'confirmed': True, 'hf_consent': True})
    assert manager.active is None
    assert not manager.plan_path.exists()


def test_second_instance_cannot_recover_or_cancel_live_preparation(manager, monkeypatch):
    manager.manager.value['workspace'] = str(manager.root / 'workspace')
    started = threading.Event()
    def probe(action):
        started.set()
        manager.cancel.wait(3)
        manager.check_cancel()
    monkeypatch.setattr(manager, 'whisper', probe)
    manager.prepare_selected({'features': ['whisper'], 'confirmed': True})
    assert started.wait(2)
    try:
        second = cm.ComponentManager(manager.setup, manager.root)
        assert second.snapshot()['preparation']['state'] == 'running'
        with pytest.raises(RuntimeError, match='другом экземпляре'):
            second.action(None, {'action': 'cancel_selected'})
    finally:
        manager.action(None, {'action': 'cancel_selected'})
        wait_plan(manager)


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


def test_reinstall_reuses_verified_model_without_requesting_token(manager, monkeypatch):
    model = manager.here / 'licensed-model'
    model.mkdir()
    (model / 'config.yaml').write_text('pipeline: local')
    manager.manager.value['diarization_model_directory'] = str(model)
    manager.manifest['diarization_model'] = {'files': []}
    monkeypatch.setattr(manager, 'verify_model', lambda path, profile: path == model)
    monkeypatch.setattr(manager, 'token', lambda value: (_ for _ in ()).throw(AssertionError('token should not be required')))
    monkeypatch.setattr(manager, 'hf_model', lambda token: (_ for _ in ()).throw(AssertionError('model should not be downloaded')))
    monkeypatch.setattr(cm.shutil, 'disk_usage', lambda path: SimpleNamespace(free=16 * 1024**3))
    monkeypatch.setattr(manager, 'diarization_runtime', lambda device, path, install: (manager.here / 'runtime/Scripts/python.exe', {'torch': 'verified'}))
    monkeypatch.setattr(manager, 'publish', lambda value: None)
    assert manager.diarization({'device': 'cpu'}, 'install')['torch'] == 'verified'
