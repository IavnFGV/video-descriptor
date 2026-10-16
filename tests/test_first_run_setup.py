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
