import importlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows-app'))
storage = importlib.import_module('storage_service')
setup_api = importlib.import_module('setup_service')


@pytest.fixture
def configured(tmp_path):
    here = tmp_path / 'application/windows-app'
    here.mkdir(parents=True)
    records = here / 'runtime/workspace'
    records.mkdir(parents=True)
    components = tmp_path / 'components'
    components.mkdir()
    manager = SimpleNamespace(value={'workspace': str(records)}, _lock=threading.RLock(),
                              operation=None, preparing=False, backends={}, runtime=here / 'runtime/backends')
    setup = setup_api.SetupService(manager, here)
    component = SimpleNamespace(root=components, active=None, plan={}, close=Mock())
    return storage.StorageService(setup, component)


def wait(service):
    deadline = time.monotonic() + 30
    while service.active and time.monotonic() < deadline:
        time.sleep(.01)
    assert not service.active
    return service.state


def transfer(service, target, kind='records'):
    service.start({'confirmed': True, 'kind': kind, 'directory': str(target)})
    return wait(service)


def restarted(service):
    saved = json.loads((service.here / 'config.local.json').read_text(encoding='utf-8'))
    service.manager.value.update(saved)
    if saved.get('records_directory'):
        service.manager.value['workspace'] = saved['records_directory']
    if saved.get('ai_components_directory'):
        service.components.root = Path(saved['ai_components_directory'])
    return storage.StorageService(service.setup, service.components)


def test_records_move_preserves_sources_settings_and_remaps_paths(configured, tmp_path):
    service = configured
    source = Path(service.manager.value['workspace'])
    media = source / 'data/uploads/record/video.mp4'
    media.parent.mkdir(parents=True)
    media.write_bytes(b'video contents')
    job = source / 'output/jobs/record/job.json'
    job.parent.mkdir(parents=True)
    job.write_text(json.dumps({'status': 'done', 'video': str(media), 'text': str(media)}), encoding='utf-8')
    (source / '.secret').write_bytes(b'protected credential payload')
    (service.here / 'config.local.json').write_text('{"port": 9123}', encoding='utf-8')
    target = tmp_path / 'Другой диск/Записи'
    assert transfer(service, target)['status'] == 'done'
    moved = json.loads((target / job.relative_to(source)).read_text(encoding='utf-8'))
    assert moved['video'] == str(target / media.relative_to(source))
    assert moved['text'] == str(media)  # Transcript text must never be rewritten.
    assert (target / '.secret').read_bytes() == b'protected credential payload'
    assert media.is_file() and service.switched and service.blocked()
    assert json.loads((service.here / 'config.local.json').read_text())['port'] == 9123
    with pytest.raises(RuntimeError):
        service.cleanup()
    after = restarted(service)
    assert after.snapshot()['records'] == str(target) and not after.blocked()
    after.cleanup()
    assert wait(after)['status'] == 'done'
    assert not media.exists() and (target / 'data/uploads/record/video.mp4').is_file()


@pytest.mark.parametrize('kind', ['records', 'components'])
def test_overlap_nonempty_busy_and_unconfirmed_do_not_change_config(configured, tmp_path, kind):
    service = configured
    current = service.components.root if kind == 'components' else Path(service.manager.value['workspace'])
    with pytest.raises(ValueError):
        transfer(service, current / 'nested', kind)
    occupied = tmp_path / 'occupied'
    occupied.mkdir()
    (occupied / 'keep').write_bytes(b'keep')
    with pytest.raises(ValueError):
        transfer(service, occupied, kind)
    with pytest.raises(ValueError):
        service.start({'kind': kind, 'directory': str(tmp_path / 'target')})
    service.manager.preparing = True
    with pytest.raises(RuntimeError):
        transfer(service, tmp_path / 'target', kind)
    assert not (service.here / 'config.local.json').exists()
    assert (occupied / 'keep').read_bytes() == b'keep'


def test_copy_failure_leaves_source_and_settings_untouched(configured, tmp_path, monkeypatch):
    source = configured.components.root
    (source / 'model.bin').write_bytes(b'model')
    monkeypatch.setattr(storage, 'digest', lambda path: 'incorrect hash')
    state = transfer(configured, tmp_path / 'new-models', 'components')
    assert state['status'] == 'error'
    assert not (configured.here / 'config.local.json').exists()
    assert (source / 'model.bin').read_bytes() == b'model'
    assert not configured.blocked()


def test_cleanup_refuses_changed_or_new_source_data(configured, tmp_path):
    source = configured.components.root
    (source / 'model.bin').write_bytes(b'model')
    assert transfer(configured, tmp_path / 'new-models', 'components')['status'] == 'done'
    service = restarted(configured)
    (source / 'new-file').write_bytes(b'new')
    service.cleanup()
    assert wait(service)['status'] == 'error'
    assert (source / 'model.bin').read_bytes() == b'model'
    (source / 'new-file').unlink()
    (source / 'model.bin').write_bytes(b'changed')
    service.cleanup()
    assert wait(service)['status'] == 'error'
    assert (source / 'model.bin').read_bytes() == b'changed'


def test_interruption_does_not_switch_to_partial_copy(configured):
    configured.state = {'status': 'running', 'source': str(configured.components.root), 'target': 'unused'}
    configured.save()
    recovered = storage.StorageService(configured.setup, configured.components)
    assert recovered.state['status'] == 'error'
    assert not recovered.blocked()
    assert not (configured.here / 'config.local.json').exists()


def test_component_paths_remapped_external_paths_preserved(configured, tmp_path):
    source = configured.components.root
    model = source / 'models/model.bin'
    model.parent.mkdir()
    model.write_bytes(b'model')
    (source / 'state.json').write_text(json.dumps({'whisper': {'model': str(model)}}))
    (configured.here / 'config.local.json').write_text(json.dumps({
        'whisper_model_directory': str(model.parent), 'npu_worker_directory': str(tmp_path / 'external'),
        'custom_key': 'preserve'}))
    target = tmp_path / 'moved-components'
    assert transfer(configured, target, 'components')['status'] == 'done'
    saved = json.loads((configured.here / 'config.local.json').read_text())
    assert saved['whisper_model_directory'] == str(target / 'models')
    assert saved['npu_worker_directory'] == str(tmp_path / 'external')
    assert saved['custom_key'] == 'preserve'
    assert json.loads((target / 'state.json').read_text())['whisper']['model'] == str(target / 'models/model.bin')


@pytest.mark.skipif(os.name != 'nt', reason='Windows venv launchers')
def test_real_venv_and_console_launcher_work_after_move(configured, tmp_path):
    env = configured.components.root / 'venv'
    subprocess.run([sys.executable, '-m', 'venv', str(env)], check=True, timeout=90)
    target = tmp_path / 'Новое место/AI'
    assert transfer(configured, target, 'components')['status'] == 'done', configured.state['message']
    output = subprocess.check_output([str(target / 'venv/Scripts/pip.exe'), '--version'], text=True, timeout=30)
    assert str(target).lower() in output.lower()


def test_component_move_rebases_saved_job_plans_on_restart(configured, tmp_path):
    source = configured.components.root
    model = source / 'models/model.bin'
    model.parent.mkdir()
    model.write_bytes(b'model')
    job = Path(configured.manager.value['workspace']) / 'output/jobs/job/job.json'
    job.parent.mkdir(parents=True)
    job.write_text(json.dumps({'status': 'done', 'device_plan': {'backends': [{'command': ['python', '--model', str(model)]}]}}))
    target = tmp_path / 'new-components'
    assert transfer(configured, target, 'components')['status'] == 'done'
    after = restarted(configured)
    assert json.loads(job.read_text())['device_plan']['backends'][0]['command'][-1] == str(target / 'models/model.bin')
    assert after.state['records_rebased']


def test_component_operation_lease_prevents_copy(configured, tmp_path):
    configured.lease_timeout = 0
    source = configured.components.root
    (source / 'model.bin').write_bytes(b'model')
    with (source / 'operation.lock').open('a+') as lease:
        storage.lock_file(lease)
        assert transfer(configured, tmp_path / 'new-components', 'components')['status'] == 'error'
    assert (source / 'model.bin').read_bytes() == b'model'
    assert not (configured.here / 'config.local.json').exists()


def test_only_path_fields_are_rewritten_not_user_content(tmp_path):
    source, target = tmp_path / 'old', tmp_path / 'new'
    text = str(source / 'example')
    value = {'text': text, 'notes': text, 'original_text': text, 'custom_prompt': text, 'path': text}
    assert storage.remap(value, source, target) == {**value, 'path': str(target / 'example')}
