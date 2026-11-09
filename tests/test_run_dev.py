import importlib.util
from pathlib import Path

import pytest


def test_preview_guard_never_adopts_production_or_other_instances(tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('run_dev', scripts / 'run_dev.py')
    dev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dev)
    config = {'records_directory': str(tmp_path)}
    owned = {'instance': 'owned', 'installation': 'source'}
    health = {'app': 'video-descriptor-windows', 'development': True,
              'workspace': str(tmp_path), **owned}
    dev.assert_owned(health, config, owned)
    for changed in [{'development': False}, {'instance': 'other'}, {'installation': 'installed'},
                    {'workspace': str(tmp_path / 'other')}]:
        with pytest.raises(ValueError, match='другим экземпляром'):
            dev.assert_owned({**health, **changed}, config, owned)
