import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('check_fast', Path(__file__).resolve().parents[1] / 'scripts/check-fast.py')
check_fast = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_fast)


def test_windows_requires_this_checkout_venv(tmp_path):
    venv = tmp_path / '.venv'
    python = venv / 'Scripts/python.exe'
    python.parent.mkdir(parents=True)
    python.touch()
    check_fast.require_windows_dev_environment(tmp_path, str(venv), 'win32', None)
    with pytest.raises(SystemExit, match='project Windows environment'):
        check_fast.require_windows_dev_environment(tmp_path, str(tmp_path / 'other'), 'win32', None)
    python.unlink()
    with pytest.raises(SystemExit, match='project Windows environment'):
        check_fast.require_windows_dev_environment(tmp_path, str(venv), 'win32', None)


def test_ci_and_non_windows_use_their_configured_python(tmp_path):
    check_fast.require_windows_dev_environment(tmp_path, str(tmp_path), 'win32', 'true')
    check_fast.require_windows_dev_environment(tmp_path, str(tmp_path), 'linux', None)
