"""The XPU workaround must preserve upstream conversion, including short turns."""
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def test_powerset_conversion_transfers_only_scores_and_mapping(monkeypatch):
    spec = importlib.util.spec_from_file_location('quality_worker', Path(__file__).resolve().parents[1] /
                                                 'windows-app/diarization_worker.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    calls = []
    expected = [0, 1, 0, 1, 0]  # Isolated one-frame replies must survive unchanged.

    class Powerset:
        def cpu(self):
            calls.append('mapping.cpu')
            return self

        def __call__(self, scores, *, soft=False):
            calls.append(('convert', scores, soft))
            return expected

    class Scores:
        def cpu(self):
            calls.append('scores.cpu')
            return 'cpu scores'

    class Module:
        pass

    module = ModuleType('pyannote.audio.utils.powerset')
    module.Powerset = Powerset
    monkeypatch.setitem(sys.modules, module.__name__, module)
    neural_model = object()
    inference = SimpleNamespace(conversion=Powerset(), model=neural_model, device='xpu')
    pipeline = SimpleNamespace(_segmentation=inference)
    worker.cpu_powerset_conversion(pipeline, SimpleNamespace(nn=SimpleNamespace(Module=Module)))
    assert inference.conversion.forward(Scores(), soft=True) is expected
    assert calls == ['mapping.cpu', 'scores.cpu', ('convert', 'cpu scores', True)]
    assert inference.model is neural_model and inference.device == 'xpu'
    pipeline._segmentation.conversion = object()
    with pytest.raises(RuntimeError, match='powerset'):
        worker.cpu_powerset_conversion(pipeline, SimpleNamespace())
