import importlib.util
import json
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('diarization_setup', Path(__file__).resolve().parents[1] /
                                              'windows-app/diarization_setup.py')
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


@pytest.mark.parametrize('requested,adapters,expected', [
    ('auto', ['Intel(R) Arc(TM) 140V GPU'], 'xpu'),
    ('auto', ['Microsoft Basic Display Adapter'], 'cpu'),
    ('auto', [], 'cpu'),
    ('auto', ['NVIDIA GeForce'], 'cpu'),  # CUDA requires a separate verified implementation.
    ('cpu', ['Intel(R) Arc(TM) 140V GPU'], 'cpu'),
    ('xpu', [], 'xpu'),  # Explicit requests are validated by torch, never silently changed.
])
def test_native_setup_selects_only_supported_backend(requested, adapters, expected):
    assert setup.choose_device(requested, adapters) == expected


@pytest.fixture
def model(tmp_path):
    directory = tmp_path / 'model'
    directory.mkdir()
    (directory / 'config.yaml').write_text('local model')
    return directory


def proof(device):
    return {'device': device, 'inference_seconds': 2, 'duration': 20,
            'turns': [{'start': 0, 'end': 1, 'speaker': 's1'}]}


def test_auto_gpu_failure_is_visible_and_explicit_gpu_never_falls_back(model, monkeypatch):
    calls = []

    def prepare(device, *args, **kwargs):
        calls.append(device)
        if device == 'xpu':
            raise RuntimeError('model operation unsupported')
        return model / 'cpu.exe', proof('cpu')

    monkeypatch.setattr(setup, 'prepare_runtime', prepare)
    result = setup.prepare('auto', model, adapters=['Intel Arc'])
    assert calls == ['xpu', 'cpu']
    assert result['diarization_device'] == 'cpu'
    assert 'model operation unsupported' in result['diarization_setup_warning']
    calls.clear()
    with pytest.raises(RuntimeError, match='unsupported'):
        setup.prepare('xpu', model, adapters=['Intel Arc'])
    assert calls == ['xpu']


def test_auto_gpu_success_pins_separate_runtime(model, monkeypatch):
    runtime = model / 'gpu.exe'
    monkeypatch.setattr(setup, 'prepare_runtime', lambda *args, **kwargs: (runtime, proof('xpu')))
    result = setup.prepare('auto', model, adapters=['Intel Arc'])
    assert result['diarization_device'] == 'xpu'
    assert result['diarization_python'] == str(runtime)
    assert result['diarization_setup_warning'] == ''
    assert setup.environment('xpu') != setup.environment('cpu')


def test_busy_runtime_is_not_modified_but_model_probe_is_required(model, tmp_path, monkeypatch):
    monkeypatch.setattr(setup, 'HERE', tmp_path)
    runtime = tmp_path / 'python.exe'
    runtime.touch()
    monkeypatch.setattr(setup, 'runtime_in_use', lambda python: True)
    calls = []

    def run(command):
        calls.append(command)
        if '--output' in command:
            Path(command[command.index('--output') + 1]).write_text(json.dumps(proof('xpu')))

    monkeypatch.setattr(setup, 'run', run)
    _, report = setup.prepare_runtime('xpu', model, install=True, python=runtime)
    assert report['device'] == 'xpu'
    assert all('pip' not in command for command in calls)
    assert any('--doctor' in command for command in calls)
    assert any('--output' in command for command in calls)


def test_stale_model_proof_cannot_hide_a_failed_probe(model, tmp_path, monkeypatch):
    monkeypatch.setattr(setup, 'HERE', tmp_path)
    runtime = tmp_path / 'python.exe'
    runtime.touch()
    output = tmp_path / 'runtime/diarization-setup/xpu/probe.json'
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps(proof('xpu')))

    def run(command):
        if '--output' in command:
            assert not output.exists()
            raise RuntimeError('probe failed')

    monkeypatch.setattr(setup, 'run', run)
    with pytest.raises(RuntimeError, match='probe failed'):
        setup.prepare_runtime('xpu', model, install=False, python=runtime)


def test_failed_setup_preserves_existing_settings(model, tmp_path, monkeypatch):
    monkeypatch.setattr(setup, 'HERE', tmp_path)
    config = tmp_path / 'config.local.json'
    before = '{"port":8780,"diarization_device":"cpu","whisper_model_directory":"keep"}'
    config.write_text(before)
    monkeypatch.setattr(sys, 'argv', ['setup', '--model', str(model), '--device', 'xpu'])

    def fail(*args, **kwargs):
        raise RuntimeError('GPU failed')

    monkeypatch.setattr(setup, 'prepare', fail)
    with pytest.raises(RuntimeError, match='GPU failed'):
        setup.main()
    assert config.read_text() == before
