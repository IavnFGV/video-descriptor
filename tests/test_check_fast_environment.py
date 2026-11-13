import argparse
import importlib.util
import os
import subprocess
import sys
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


@pytest.mark.parametrize('value', ['0', '-1', 'auto', '1.5'])
def test_worker_count_must_be_positive(value):
    with pytest.raises(argparse.ArgumentTypeError):
        check_fast.positive_workers(value)


def test_test_phases_are_explicit(monkeypatch):
    commands = []
    monkeypatch.setattr(check_fast, 'run', lambda *args: commands.append(args))
    check_fast.run_tests(None)
    assert len(commands) == 1
    assert '-n' not in commands[0]
    assert commands[0][-1] == '--ignore=tests/test_ci_policy.py'

    commands.clear()
    check_fast.run_tests(4)
    assert len(commands) == 2
    parallel, serial = commands
    assert parallel[parallel.index('-n') + 1] == '4'
    assert all(f'--ignore={path}' in parallel for path in check_fast.PORT_SENSITIVE_TESTS)
    assert serial[-2:] == check_fast.PORT_SENSITIVE_TESTS
    assert '-n' not in serial


def test_run_removes_inherited_pytest_options(monkeypatch):
    captured = {}
    monkeypatch.setenv('PYTEST_ADDOPTS', '-n 8 -k nothing')
    monkeypatch.setattr(check_fast.subprocess, 'run', lambda *args, **kwargs: captured.update(kwargs))
    check_fast.run('example')
    assert 'PYTEST_ADDOPTS' not in captured['env']
    assert os.environ['PYTEST_ADDOPTS'] == '-n 8 -k nothing'


def test_serial_phase_runs_after_parallel_failure(monkeypatch):
    commands = []

    def run(*args):
        commands.append(args)
        if '-n' in args:
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(check_fast, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        check_fast.run_tests(2)
    assert len(commands) == 2
    assert commands[1][-2:] == check_fast.PORT_SENSITIVE_TESTS


def test_parallel_and_serial_collections_partition_default_suite():
    env = os.environ.copy()
    env.pop('PYTEST_ADDOPTS', None)

    def collect(*args):
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider', *args],
            cwd=check_fast.ROOT, env=env, capture_output=True, text=True, check=True,
        )
        return [line for line in result.stdout.splitlines() if line.startswith('tests/') and '::' in line]

    default = collect('--ignore=tests/test_ci_policy.py')
    parallel = collect('--ignore=tests/test_ci_policy.py',
                       *(f'--ignore={path}' for path in check_fast.PORT_SENSITIVE_TESTS))
    serial = collect(*check_fast.PORT_SENSITIVE_TESTS)
    assert default and parallel and serial
    assert len(default) == len(set(default))
    assert len(parallel + serial) == len(set(parallel + serial))
    assert set(default) == set(parallel + serial)
