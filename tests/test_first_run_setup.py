import importlib
import importlib.util
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'windows-app'))
setup_api = importlib.import_module('setup_service')
compute_module = importlib.import_module('compute')


@pytest.fixture
def configured(tmp_path):
    model = tmp_path / 'Модели Whisper'
    model.mkdir()
    for name in ('encoder_model', 'decoder_model', 'tokenizer', 'detokenizer'):
        for extension in ('xml', 'bin'):
            (model / f'openvino_{name}.{extension}').write_bytes(b'test IR payload')
    for name in ('generation_config', 'preprocessor_config', 'tokenizer_config', 'tokenizer'):
        (model / f'{name}.json').write_text('{}')
    (model / 'config.json').write_text(json.dumps({'encoder_layers': 12, 'vocab_size': 51865}))
    digest = setup_api.model_digest(model)
    (tmp_path / 'component-manifest.json').write_text(json.dumps({'whisper_model': {'engine_digest_sha256': digest}}))
    value = {'workspace': str(tmp_path / 'runtime/workspace'), 'npu_worker_directory': str(tmp_path / 'benchmark'),
             'npu_url': 'http://127.0.0.1:8766'}
    manager = compute_module.ComputeManager(value, tmp_path)
    return tmp_path, model, manager, setup_api.SetupService(manager, tmp_path)


def test_model_import_preserves_config_and_updates_manager_without_restart(configured):
    here, model, manager, service = configured
    (here / 'config.local.json').write_text(json.dumps({'port': 9123, 'ollama_model': 'keep-existing'}))
    old_backend = dict(manager.backends['CPU'])
    result = service.apply(str(model))
    saved = json.loads((here / 'config.local.json').read_text())
    assert saved['port'] == 9123 and saved['ollama_model'] == 'keep-existing'
    assert saved['whisper_model_directory'] == str(model)
    assert manager.model == model and service.snapshot()['verified']
    assert manager.backends['CPU']['expected_model_sha256'] == result['sha256']
    assert str(model) in manager.backends['CPU']['command']
    assert 'expected_model_sha256' not in old_backend
    assert compute_module.ComputeManager({**manager.value, **saved}, here).model == model


def test_mutated_model_and_wrong_model_are_rejected(configured):
    here, model, _, service = configured
    (model / 'openvino_decoder_model.bin').write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='отличаются'):
        service.apply(str(model))
    assert not (here / 'config.local.json').exists()
    (model / 'config.json').write_text(json.dumps({'encoder_layers': 6, 'vocab_size': 51865}))
    with pytest.raises(ValueError, match='многоязычная'):
        service.apply(str(model))


def test_busy_queue_and_damaged_config_are_preserved(configured):
    here, model, manager, service = configured
    job = Path(manager.value['workspace']) / 'output/jobs/running/job.json'
    job.parent.mkdir(parents=True)
    job.write_text('{"status":"running"}')
    with pytest.raises(RuntimeError, match='Дождитесь'):
        service.apply(str(model))
    job.write_text('{"status":"done"}')
    (here / 'config.local.json').write_text('{damaged')
    with pytest.raises(ValueError):
        service.apply(str(model))
    assert (here / 'config.local.json').read_text() == '{damaged'


def test_invalid_model_config_and_removed_model_have_clear_state(configured):
    here, model, _, service = configured
    service.apply(str(model))
    (model / 'config.json').write_text('[]')
    with pytest.raises(ValueError, match='многоязычная'):
        setup_api.inspect_model(str(model), here)
    (model / 'config.json').unlink()
    assert not service.snapshot()['verified']


def test_running_worker_with_another_model_is_rejected(monkeypatch):
    from io import BytesIO
    from unittest.mock import MagicMock

    from video_descriptor import local_backends

    profile = {'protocol': 1, 'device': 'CPU', 'model': 'small', 'multilingual': True,
               'pipeline': 'dynamic', 'num_beams': 1, 'model_sha256': 'other-model'}
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value = BytesIO(json.dumps(profile).encode())
    monkeypatch.setattr(local_backends.urllib.request, 'build_opener', lambda *args: opener)
    with pytest.raises(local_backends.BackendUnavailable):
        local_backends.engine_info({'device': 'CPU', 'url': 'http://127.0.0.1:8767',
                                    'expected_model_sha256': 'selected-model'})


@pytest.mark.parametrize('path', ['', 'relative/model', r'\\server\share\model', None])
def test_model_path_validation_rejects_empty_relative_and_network_paths(configured, path):
    here, _, _, _ = configured
    with pytest.raises(ValueError):
        setup_api.inspect_model(path, here)


def test_setup_api_requires_instance_and_origin_and_saves_valid_model(configured, monkeypatch):
    here, model, manager, _ = configured
    spec = importlib.util.spec_from_file_location('setup_native_app', ROOT / 'windows-app/app.py')
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    monkeypatch.setattr(app, 'HERE', here)
    with ThreadingHTTPServer(('127.0.0.1', 0), app.make_handler(manager.value, 'instance')) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            assert requests.post(base + '/api/setup/model', json={'path': str(model)}, timeout=5).status_code == 403
            assert requests.post(base + '/api/setup/ollama', json={'model': 'test'}, timeout=5).status_code == 403
            headers = {'X-App-Instance': 'instance', 'Origin': 'https://foreign.invalid'}
            assert requests.post(base + '/api/setup/model', headers=headers, json={'path': str(model)}, timeout=5).status_code == 403
            headers = {'X-App-Instance': 'instance'}
            assert requests.post(base + '/api/setup/model', headers=headers, json=[], timeout=5).status_code == 400
            response = requests.post(base + '/api/setup/model', headers=headers, json={'path': str(model)}, timeout=5)
            assert response.status_code == 200 and response.json()['verified']
            assert requests.get(base + '/api/setup', timeout=5).json()['verified']
        finally:
            server.shutdown()
            thread.join()


def test_ollama_service_without_selected_model_is_not_ready(configured, monkeypatch):
    _, _, manager, _ = configured
    manager.value['ollama_model'] = 'missing:9b'
    monkeypatch.setattr(setup_api, 'ollama_request', lambda *args: {'models': [{'name': 'present:9b', 'size': 1024}]})
    status = setup_api.ollama_status(manager.value)
    assert status['service_ready'] and not status['ready']
    assert status['models'] == [{'name': 'present:9b', 'bytes': 1024}]


def test_ollama_selection_uses_existing_translation_settings_and_preserves_secret(configured, monkeypatch):
    from video_descriptor import translation_settings

    _, _, manager, _ = configured
    root = manager.value['workspace']
    translation_settings.save(root, {'api_key': 'keep-private', 'billing_mode': 'free'})

    def request(value, endpoint, body=None):
        return {'models': [{'name': 'language:9b'}]} if endpoint == '/api/tags' else {'capabilities': ['completion']}

    monkeypatch.setattr(setup_api, 'ollama_request', request)
    result = setup_api.select_ollama(manager.value, 'language:9b')
    saved = translation_settings.load(root)
    assert saved['provider'] == 'ollama' and saved['ollama_model'] == 'language:9b'
    assert saved['api_key'] == 'keep-private' and saved['billing_mode'] == 'free'
    assert 'api_key' not in result
    assert setup_api.ollama_status(manager.value)['ready']


def test_ollama_embedding_and_uninstalled_models_cannot_be_selected(configured, monkeypatch):
    _, _, manager, _ = configured
    monkeypatch.setattr(setup_api, 'ollama_request', lambda value, endpoint, body=None:
                        {'models': [{'name': 'embedding:latest'}]} if endpoint == '/api/tags' else
                        {'capabilities': ['embedding']})
    with pytest.raises(ValueError, match='генерацию текста'):
        setup_api.select_ollama(manager.value, 'embedding:latest')
    with pytest.raises(ValueError, match='из списка'):
        setup_api.select_ollama(manager.value, 'not-installed:9b')
    assert not (Path(manager.value['workspace']) / '.devcontainer/translation-settings.json').exists()


def test_stopped_ollama_reports_a_recoverable_state(configured, monkeypatch):
    _, _, manager, _ = configured

    def stopped(*args):
        raise requests.ConnectionError('stopped')

    monkeypatch.setattr(setup_api, 'ollama_request', stopped)
    status = setup_api.ollama_status(manager.value)
    assert not status['ready'] and not status['service_ready'] and status['models'] == []


def wait_setup(service):
    import time
    deadline = time.monotonic() + 5
    while service.manager.operation and time.monotonic() < deadline:
        time.sleep(.01)
    assert service.manager.operation is None
    return service.state


def fake_download(configured, monkeypatch):
    import hashlib
    from unittest.mock import MagicMock

    import model_download
    here, model, _, _ = configured
    payloads = {p.name: p.read_bytes() for p in model.iterdir()}
    profile = {'source': 'https://huggingface.co/OpenVINO/whisper-small-fp16-ov', 'revision': 'a' * 40,
               'files': [{'name': n, 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
                         for n, b in payloads.items()], 'engine_digest_sha256': setup_api.model_digest(model)}
    (here / 'component-manifest.json').write_text(json.dumps({'whisper_model': profile}))
    calls = []

    def get(url, **kwargs):
        name = url.rsplit('/', 1)[-1]
        calls.append(name)
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_content.return_value = [payloads[name]]
        return response

    session = MagicMock()
    session.__enter__.return_value = session
    session.get.side_effect = get
    monkeypatch.setattr(model_download.requests, 'Session', lambda: session)
    return profile, calls, session, payloads


def test_confirmed_download_verifies_and_atomically_publishes(configured, monkeypatch):
    here, _, manager, service = configured
    profile, calls, _, _ = fake_download(configured, monkeypatch)
    with pytest.raises(ValueError, match='Подтвердите'):
        service.download(False)
    assert not calls
    assert service.download(True)['status'] == 'running'
    assert wait_setup(service)['status'] == 'done'
    assert len(calls) == len(profile['files'])
    assert manager.model.name == 'whisper-small-' + 'a' * 40
    assert setup_api.inspect_model(str(manager.model), here)['verified']
    assert not (manager.model.parent / ('.whisper-small-' + 'a' * 40 + '.partial')).exists()
    assert service.snapshot()['verified']


def test_interrupted_download_reuses_only_verified_files(configured, monkeypatch):
    import model_download
    here, _, _, service = configured
    profile, calls, session, _ = fake_download(configured, monkeypatch)
    good_get = session.get.side_effect
    interrupted = profile['files'][1]['name']

    def broken(url, **kwargs):
        if url.endswith('/' + interrupted):
            raise requests.ConnectionError('interrupted')
        return good_get(url, **kwargs)

    session.get.side_effect = broken
    service.download(True)
    assert wait_setup(service)['status'] == 'error'
    assert not (here / 'runtime/models' / ('whisper-small-' + 'a' * 40)).exists()
    session.get.side_effect = good_get
    service.download(True)
    assert wait_setup(service)['status'] == 'done'
    assert calls.count(profile['files'][0]['name']) == 1
    assert model_download.checksum(service.manager.model / interrupted) == profile['files'][1]['sha256']


def test_download_hash_mismatch_never_publishes_or_changes_settings(configured, monkeypatch):
    here, model, manager, service = configured
    _, _, _, payloads = fake_download(configured, monkeypatch)
    name = next(iter(payloads))
    payloads[name] = b'X' * len(payloads[name])
    before = manager.model
    service.download(True)
    state = wait_setup(service)
    assert state['status'] == 'error' and 'контрольная сумма' in state['message']
    assert manager.model == before and model.is_dir()
    assert not (here / 'config.local.json').exists()


@pytest.mark.parametrize('name', ['../escape', 'D:escape', '..\\escape', '/escape'])
def test_downloader_rejects_path_traversal(configured, monkeypatch, name):
    import model_download
    here, _, _, _ = configured
    profile, calls, _, _ = fake_download(configured, monkeypatch)
    profile['files'][0]['name'] = name
    with pytest.raises(ValueError, match='Unsafe'):
        model_download.download_profile(profile, here / 'models', lambda *args: None)
    assert not calls


def test_conflicting_setup_operations_and_retry(configured):
    _, model, manager, service = configured
    release = threading.Event()
    service.start('download', lambda: release.wait(3))
    try:
        with pytest.raises(RuntimeError, match='Дождитесь'):
            service.download(True)
        with pytest.raises(RuntimeError, match='Дождитесь'):
            service.apply(str(model))
        with pytest.raises(RuntimeError, match='Дождитесь'):
            manager.prepare()
        with pytest.raises(RuntimeError, match='Дождитесь'):
            manager.save({'speech_device': 'CPU'})
    finally:
        release.set()
        wait_setup(service)
    service.apply(str(model))
    service.complete()
    assert setup_api.SetupService(manager, service.here).snapshot()['completed']


@pytest.mark.parametrize('inventory,expected', [
    ({'devices': ['CPU', 'GPU', 'NPU'], 'model_present': True}, False),
    ({'devices': ['CPU'], 'model_present': False, 'openvino': 'v', 'genai': 'v'}, False),
    ({'devices': ['CPU'], 'model_present': True, 'openvino': 'v', 'genai': 'v'}, True),
])
def test_hardware_runtime_model_and_ready_are_distinct(configured, monkeypatch, inventory, expected):
    from video_descriptor.local_backends import BackendUnavailable
    _, _, manager, _ = configured
    manager._inventory = inventory
    monkeypatch.setattr(compute_module, 'engine_info', lambda *a, **k: (_ for _ in ()).throw(BackendUnavailable('offline')))
    cap = manager.capabilities()['CPU']
    assert cap['available'] is expected
    assert not cap['ready'] and not cap['service_ready']
    assert cap['detected'] and cap['model_present'] == inventory['model_present']


def test_gemini_refusal_is_redacted_and_does_not_generate(configured, monkeypatch):
    from video_descriptor import gemini, translation_settings
    _, _, manager, service = configured
    service.gemini({'api_key': 'super-secret', 'model': 'gemini-test'})
    calls = []

    def rejected(*args, **kwargs):
        calls.append(args)
        raise gemini.GeminiServiceError('super-secret provider failure')

    monkeypatch.setattr(gemini, 'models', rejected)
    with pytest.raises(ValueError) as error:
        service.gemini({'check': True})
    assert 'super-secret' not in str(error.value)
    assert calls == [('super-secret',)]
    assert translation_settings.load(manager.value['workspace'])['api_key'] == 'super-secret'
    assert 'api_key' not in service.diagnostics()['gemini']


def test_ollama_notes_selection_does_not_change_translation(configured, monkeypatch):
    from video_descriptor import translation_settings
    _, _, manager, _ = configured
    monkeypatch.setattr(setup_api, 'validate_ollama_model', lambda *args: None)
    setup_api.select_ollama(manager.value, 'translate:9b')
    setup_api.select_ollama(manager.value, 'notes:9b', 'notes')
    assert translation_settings.load(manager.value['workspace'])['ollama_model'] == 'translate:9b'
    path = Path(manager.value['workspace']) / '.devcontainer/notes-settings.json'
    assert json.loads(path.read_text())['ollama_model'] == 'notes:9b'


def test_probe_rejects_invalid_audio_without_starting_work(configured):
    _, _, manager, service = configured
    with pytest.raises(ValueError, match='WAV'):
        service.probe(b'not wave')
    assert manager.operation is None


def test_probe_uses_packaged_sample_without_file_selection(configured, monkeypatch):
    import shutil

    here, _, _, service = configured
    shutil.copytree(ROOT / 'windows-app/samples', here / 'samples')
    calls = []
    monkeypatch.setattr(service, 'start', lambda kind, work, message: calls.append((kind, message)))
    service.probe()
    assert calls[0][0] == 'probe'
    assert 'Распознаём' in calls[0][1]


@pytest.mark.parametrize(('channels', 'width', 'rate', 'seconds', 'reason'), [
    (2, 2, 16000, 1, 'каналов: 2'),
    (1, 1, 16000, 1, 'разрядность: 8'),
    (1, 2, 22050, 1, 'частота: 22050'),
    (1, 2, 16000, 16, 'длительность: 16.0'),
])
def test_probe_explains_incompatible_audio_without_changing_it(configured, channels, width, rate, seconds, reason):
    import io
    import wave

    _, _, manager, service = configured
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setparams((channels, width, rate, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0' * (channels * width * rate * seconds))
    data = output.getvalue()
    with pytest.raises(ValueError, match=reason):
        service.probe(data)
    assert manager.operation is None
    assert output.getvalue() == data


def test_release_includes_only_named_sample_files():
    spec = importlib.util.spec_from_file_location('sample_release', ROOT / 'windows-app/build_release.py')
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    samples = {path.name for path in build.source_paths() if path.parent.name == 'samples'}
    assert samples == {'speech-check.wav', 'speech-check.mp4', 'README.md'}


def test_builtin_probe_http_uses_server_sample(configured, monkeypatch):
    here, _, manager, _ = configured
    spec = importlib.util.spec_from_file_location('builtin_probe_app', ROOT / 'windows-app/app.py')
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    monkeypatch.setattr(app, 'HERE', here)
    calls = []

    def probe(self, audio=None):
        calls.append(audio)
        return {'status': 'running'}

    monkeypatch.setattr(setup_api.SetupService, 'probe', probe)
    with ThreadingHTTPServer(('127.0.0.1', 0), app.make_handler(manager.value, 'instance')) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            response = requests.post(f'http://127.0.0.1:{server.server_port}/api/setup/probe',
                                     json={}, headers={'X-App-Instance': 'instance'}, timeout=5)
            assert response.status_code == 202
            assert calls == [None]
        finally:
            server.shutdown()
            thread.join()


def test_windows_key_encryption_at_rest_roundtrip(tmp_path):
    import os

    from video_descriptor import translation_settings
    if os.name != 'nt':
        pytest.skip('Windows DPAPI')
    result = translation_settings.save(tmp_path, {'provider': 'gemini', 'api_key': 'secret-test-value'})
    path = tmp_path / '.devcontainer/translation-settings.json'
    assert 'secret-test-value' not in path.read_text()
    assert json.loads(path.read_text())['api_key_dpapi']
    assert translation_settings.load(tmp_path)['api_key'] == 'secret-test-value'
    assert result['has_key'] and 'api_key_dpapi' not in result


@pytest.mark.parametrize('endpoint', ['download', 'probe', 'complete', 'gemini', 'refresh'])
def test_new_setup_mutations_require_instance(configured, monkeypatch, endpoint):
    here, _, manager, _ = configured
    spec = importlib.util.spec_from_file_location('protected_setup_app', ROOT / 'windows-app/app.py')
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    monkeypatch.setattr(app, 'HERE', here)
    with ThreadingHTTPServer(('127.0.0.1', 0), app.make_handler(manager.value, 'instance')) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            response = requests.post(f'http://127.0.0.1:{server.server_port}/api/setup/{endpoint}',
                                     json={'confirmed': True, 'api_key': 'never-save'}, timeout=5)
            assert response.status_code == 403
            assert not (here / 'config.local.json').exists()
            assert not (Path(manager.value['workspace']) / '.devcontainer/translation-settings.json').exists()
        finally:
            server.shutdown()
            thread.join()


def test_pnp_inventory_does_not_imply_runtime_or_inference(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(setup_api.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        stdout=json.dumps({'intel_gpu': ['Intel Arc'], 'intel_npu': ['Intel AI Boost']})))
    result = setup_api.hardware_inventory()
    import os
    if os.name == 'nt':
        assert result['intel_npu'] == ['Intel AI Boost'] and result['intel_gpu'] == ['Intel Arc']
    assert 'ready' not in result


def test_ollama_show_failure_keeps_installed_models_selectable(configured, monkeypatch):
    _, _, manager, _ = configured
    manager.value['ollama_model'] = 'present:9b'

    def request(value, endpoint, body=None):
        if endpoint == '/api/version':
            return {'version': 'test'}
        if endpoint == '/api/tags':
            return {'models': [{'name': 'present:9b'}]}
        raise requests.HTTPError('show unavailable')

    monkeypatch.setattr(setup_api, 'ollama_request', request)
    status = setup_api.ollama_status(manager.value)
    assert status['service_ready'] and status['model_present'] and not status['ready']
    assert status['models'][0]['name'] == 'present:9b'


def test_bootstrap_is_nonblocking_once_and_preserves_explicit_device(configured, monkeypatch):
    _, model, manager, service = configured
    manager.model = model
    service.apply(str(model))
    manager.save({'speech_device': 'CPU'})
    entered, release = threading.Event(), threading.Event()
    calls = []

    def inventory():
        entered.set()
        release.wait(3)
        return {}

    monkeypatch.setattr(manager, 'inventory', inventory)
    monkeypatch.setattr(manager, 'prepare', lambda: calls.append(manager.settings()['speech_device']))
    monkeypatch.setattr(setup_api, 'ollama_status', lambda value: {'selected': 'saved', 'models': []})
    service.bootstrap()
    assert entered.wait(1)
    service.bootstrap()
    assert calls == []
    assert service.snapshot()['bootstrap']['status'] == 'checking'
    release.set()
    import time
    deadline = time.monotonic() + 3
    while service.bootstrap_state['status'] == 'checking' and time.monotonic() < deadline:
        time.sleep(.01)
    assert calls == ['CPU']
    assert service.bootstrap_state['status'] == 'done'


def test_bootstrap_optional_discovery_survives_broken_speech(configured, monkeypatch):
    _, _, manager, service = configured
    seen = threading.Event()
    monkeypatch.setattr(manager, 'inventory', lambda: (_ for _ in ()).throw(ValueError('broken runtime')))
    monkeypatch.setattr(setup_api, 'ollama_status', lambda value: (seen.set() or {'selected': 'saved', 'models': []}))
    service.bootstrap()
    assert seen.wait(3)
    import time
    deadline = time.monotonic() + 3
    while service.bootstrap_state['status'] == 'checking' and time.monotonic() < deadline:
        time.sleep(.01)
    assert service.bootstrap_state['status'] == 'error'
