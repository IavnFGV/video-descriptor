import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture
def modules(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    loaded = []
    for name in ('local_build', 'clean_local'):
        spec = importlib.util.spec_from_file_location(name, scripts / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        loaded.append(module)
    return loaded


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo with spaces'
    root.mkdir()
    subprocess.run(['git', 'init', '-b', 'main', str(root)], check=True, capture_output=True)
    for key, value in [('user.name', 'Local test'), ('user.email', 'test@example.invalid')]:
        subprocess.run(['git', '-C', str(root), 'config', key, value], check=True)
    (root / 'keep.log').write_text('tracked')
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(root), 'commit', '-m', 'fixture'], check=True, capture_output=True)
    return root


def test_local_build_lock_releases_after_failure(modules, tmp_path):
    build, _ = modules
    with pytest.raises(RuntimeError), build.build_lock(tmp_path) as acquired:
        assert acquired
        with build.build_lock(tmp_path) as second:
            assert not second
        raise RuntimeError('crashed worker')
    with build.build_lock(tmp_path) as acquired:
        assert acquired


def test_queue_drains_commit_arriving_during_build(modules, tmp_path, monkeypatch):
    build, _ = modules
    state = tmp_path / 'state'
    first, second = 'a' * 40, 'b' * 40
    build.write_json(state / 'queue' / (first + '.json'), {'commit': first})
    calls = []

    def run(repo, state, config, sha):
        calls.append(sha)
        if sha == first:
            build.write_json(state / 'queue' / (second + '.json'), {'commit': second})
        return True

    monkeypatch.setattr(build, 'run_build', run)
    assert build.drain(tmp_path, state, {})
    assert calls == [first, second]
    assert not list((state / 'queue').iterdir())


def test_reuse_requires_exact_artifact_hash(modules, tmp_path):
    build, _ = modules
    package = tmp_path / 'package.zip'
    package.write_bytes(b'verified')
    record = {'state': 'ready', 'artifacts': [{'path': str(package), 'sha256': build.digest(package)}]}
    assert build.reusable(record)
    package.write_bytes(b'corrupt')
    assert not build.reusable(record)


def test_failed_checks_do_not_build_or_claim_success(modules, tmp_path, monkeypatch):
    build, _ = modules
    sdk = tmp_path / 'sdk'
    sdk.mkdir()
    (sdk / 'desktop-build.json').write_text(json.dumps({'source_sha256': 'hash', 'sdk_sha256': 'sdk'}))
    calls = []

    def command(args, **kwargs):
        calls.append(args)
        if 'worktree' in args:
            source = Path(args[-2])
            (source / 'windows-app').mkdir(parents=True)
            (source / 'windows-app/release-inputs.json').write_text(json.dumps({'version': '1.0.0', 'webview2': {'sha256': 'sdk'}}))
        else:
            raise subprocess.CalledProcessError(2, args)

    monkeypatch.setattr(build, 'digest', lambda path: 'hash')
    monkeypatch.setattr(build.subprocess, 'run', command)
    config = {'output': str(tmp_path / 'output'), 'desktop_sdk': str(sdk), 'python': 'python', 'cache': 'cache', 'iscc': 'iscc'}
    state = tmp_path / 'state'
    assert not build.run_build(tmp_path, state, config, 'a' * 40)
    report = json.loads((state / 'status.json').read_text())
    assert report['state'] == 'failed' and report['stage'] == 'checks'
    assert len(calls) == 2
    assert calls[0][-1] == 'a' * 40
    assert not list((tmp_path / 'output').rglob('*.exe'))


def test_existing_hook_is_preserved(modules, repo):
    build, _ = modules
    hook = repo / '.git/hooks/post-merge'
    hook.write_text('# existing custom hook\n')
    with pytest.raises(ValueError, match='preserved'):
        build.install_hook(repo)
    assert hook.read_text() == '# existing custom hook\n'


@pytest.mark.skipif(os.name != 'nt', reason='Real inbox PowerShell/Git hook on Windows')
def test_actual_post_merge_hook_runs_only_on_local_main(modules, repo):
    build, _ = modules
    scripts = repo / 'scripts'
    scripts.mkdir()
    (scripts / 'Build-Local.ps1').write_text(
        'param([switch]$Background)\nSet-Content -LiteralPath (Join-Path $PSScriptRoot "../.git/hook-fired") -Value yes\n')
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-m', 'hook fixture'], check=True, capture_output=True)
    build.install_hook(repo)
    subprocess.run(['git', '-C', str(repo), 'checkout', '-b', 'topic'], check=True, capture_output=True)
    (repo / 'change.txt').write_text('change')
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-m', 'change'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repo), 'checkout', 'main'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repo), 'merge', '--ff-only', 'topic'], check=True, capture_output=True)
    assert (repo / '.git/hook-fired').read_text().strip() == 'yes'


def test_cleanup_preserves_latest_versions_models_and_tracked_files(modules, repo, tmp_path):
    _, clean = modules
    packages = []
    for number in range(1, 6):
        folder = repo / 'dist' / f'0.8.{number}'
        folder.mkdir(parents=True)
        package = folder / f'VideoDescriptor-0.8.{number}-windows-x64-setup.exe'
        package.write_bytes(b'installer')
        packages.append(package)
    log = repo / 'old.log'
    log.write_text('untracked')
    cache = tmp_path / 'cache'
    payload = cache / 'payload-fixture'
    payload.mkdir(parents=True)
    (payload / 'temporary').write_bytes(b'temp')
    model = cache / 'models/keep.bin'
    model.parent.mkdir()
    model.write_bytes(b'keep')
    old = time.time() - 30 * 86400
    for path in (log, repo / 'keep.log', payload):
        os.utime(path, (old, old))
    report = clean.plan(repo, {'cache': str(cache)})
    assert report['preserved_versions'] == ['0.8.3', '0.8.4', '0.8.5']
    assert all(path.exists() for path in packages), 'Preview must not delete'
    clean.apply_plan(report)
    assert not packages[0].exists() and not packages[1].exists()
    assert all(p.exists() for p in packages[2:])
    assert model.exists() and (repo / 'keep.log').exists()
    assert not payload.exists() and not log.exists()


def test_cleanup_changed_target_refuses_entire_plan(modules, repo):
    _, clean = modules
    log = repo / 'old.log'
    log.write_text('old')
    old = time.time() - 30 * 86400
    os.utime(log, (old, old))
    report = clean.plan(repo, {})
    log.write_text('new content')
    with pytest.raises(ValueError, match='changed'):
        clean.apply_plan(report)
    assert log.read_text() == 'new content'


def test_cleanup_refuses_linked_content(modules, tmp_path, monkeypatch):
    _, clean = modules
    folder = tmp_path / 'payload'
    folder.mkdir()
    item = folder / 'junction'
    item.mkdir()
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda path: path == item or original(path))
    with pytest.raises(ValueError, match='Linked content'):
        clean.safe_size(folder)


def test_cleanup_boundary_cannot_be_bypassed(modules, tmp_path):
    _, clean = modules
    outside = tmp_path / 'valuable'
    outside.write_text('preserve')
    with pytest.raises(ValueError, match='boundary'):
        clean.apply_plan({'files': [{'path': str(outside), 'boundary': str(tmp_path / 'allowed')}]})
    assert outside.exists()
