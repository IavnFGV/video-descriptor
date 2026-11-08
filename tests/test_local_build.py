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


def test_queue_keeps_domestic_and_standard_requests_for_same_commit(modules, tmp_path, monkeypatch):
    build, _ = modules
    state, sha = tmp_path / 'state', 'a' * 40
    build.write_json(state / 'queue' / (sha + '.json'), {'commit': sha})
    build.write_json(state / 'queue' / (sha + '-domestic.json'), {'commit': sha, 'domestic': True})
    profiles = []

    def run(repo, state, config, commit):
        assert commit == sha
        profiles.append(config['domestic'])
        return True

    monkeypatch.setattr(build, 'run_build', run)
    assert build.drain(tmp_path, state, {})
    assert sorted(profiles) == [False, True]


def test_reuse_requires_exact_artifact_hash(modules, tmp_path):
    build, _ = modules
    package = tmp_path / 'package.zip'
    package.write_bytes(b'verified')
    record = {'state': 'ready', 'artifacts': [{'path': str(package), 'sha256': build.digest(package)}]}
    assert build.reusable(record)
    package.write_bytes(b'corrupt')
    assert not build.reusable(record)


def test_live_status_page_links_downloads_and_escapes_errors(modules, tmp_path):
    build, _ = modules
    state, output = tmp_path / 'state', tmp_path / 'local'
    package = output / '0.8.22/VideoDescriptor-0.8.22-windows-x64-setup.exe'
    package.parent.mkdir(parents=True)
    package.write_bytes(b'fixture')
    ready = {'state':'ready','stage':'done','version':'0.8.22','commit':'a'*40,
             'artifacts':[{'path':str(package)}]}
    build.update_status(state, {'output':str(output)}, ready)
    page = (output / 'build-status.html').read_text(encoding='utf-8')
    assert 'http-equiv="refresh"' in page and 'content="3"' in page
    assert package.as_uri() in page and '0.8.22' in page
    build.update_status(state, {'output':str(output)}, {
        'state':'failed','stage':'checks','error':'<script>unsafe</script>'})
    page = (output / 'build-status.html').read_text(encoding='utf-8')
    assert '&lt;script&gt;unsafe&lt;/script&gt;' in page
    assert '<script>unsafe</script>' not in page
    assert package.as_uri() in page, 'Last successful downloads remain clearly labeled'


def test_status_publish_retries_transient_windows_file_lock(modules, tmp_path, monkeypatch):
    build, _ = modules
    replace = build.os.replace
    calls = []

    def transient(source, destination):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError('reader holds status file')
        replace(source, destination)

    monkeypatch.setattr(build.os, 'replace', transient)
    build.write_json(tmp_path / 'status.json', {'state': 'ready'})
    assert len(calls) == 2
    assert json.loads((tmp_path / 'status.json').read_text()) == {'state': 'ready'}


def test_domestic_build_keeps_existing_dashboard_location(modules, tmp_path):
    build, _ = modules
    output = tmp_path / 'local'
    build.update_status(tmp_path / 'state', {'output': str(output / 'domestic'), 'status_output': str(output)},
                        {'state': 'running', 'stage': 'build'})
    assert (output / 'build-status.html').is_file()
    assert not (output / 'domestic/build-status.html').exists()


def test_ready_downloads_are_published_under_version(modules, tmp_path):
    build, _ = modules
    staging = tmp_path / 'internal/artifacts'
    staging.mkdir(parents=True)
    package = staging / 'VideoDescriptor-0.8.18-windows-x64.zip'
    package.write_bytes(b'verified package')
    record = {'state':'ready', 'version':'0.8.18', 'commit':'a'*40, 'output':str(staging),
              'artifacts':[{'path':str(package), 'sha256':build.digest(package)}]}
    result = build.publish_ready(record, tmp_path / 'local')
    assert result['output'] == str(tmp_path / 'local/0.8.18')
    assert build.reusable(result)
    assert json.loads((tmp_path / 'local/0.8.18/provenance.json').read_text())['commit'] == 'a'*40
    assert package.exists(), 'Internal verification evidence remains available'


def test_cleanup_counts_versioned_local_downloads(modules, repo):
    _, clean = modules
    for number in range(1, 5):
        folder = repo / 'dist/local' / f'0.8.{number}'
        folder.mkdir(parents=True)
        (folder / f'VideoDescriptor-0.8.{number}-windows-x64.zip').write_bytes(b'package')
    result = clean.plan(repo, {})
    assert result['preserved_versions'] == ['0.8.2', '0.8.3', '0.8.4']
    assert len(result['files']) == 1
    assert Path(result['files'][0]['path']).parent.name == '0.8.1'


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
    config = {'output': str(tmp_path / 'output'), 'desktop_sdk': str(sdk), 'python': 'python', 'cache': str(tmp_path / 'cache'), 'iscc': 'iscc'}
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
        'param([switch]$Background, [switch]$Domestic)\n'
        'if ($env:GIT_DIR -or $env:GIT_INDEX_FILE) { throw "Inherited Git state" }\n'
        'Set-Content -LiteralPath (Join-Path $PSScriptRoot "../.git/hook-fired") -Value yes\n')
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
    private = repo / '.env.private.log'
    private.write_text('preserve configuration')
    cache = tmp_path / 'cache'
    payload = cache / 'payload-fixture'
    payload.mkdir(parents=True)
    (payload / 'temporary').write_bytes(b'temp')
    model = cache / 'models/keep.bin'
    model.parent.mkdir()
    model.write_bytes(b'keep')
    old = time.time() - 30 * 86400
    for path in (log, private, repo / 'keep.log', payload):
        os.utime(path, (old, old))
    report = clean.plan(repo, {'cache': str(cache)})
    assert report['preserved_versions'] == ['0.8.3', '0.8.4', '0.8.5']
    assert all(path.exists() for path in packages), 'Preview must not delete'
    clean.apply_plan(report)
    assert not packages[0].exists() and not packages[1].exists()
    assert all(p.exists() for p in packages[2:])
    assert model.exists() and (repo / 'keep.log').exists()
    assert private.exists()
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


def test_status_excludes_active_request_and_shows_live_packaging_details(modules, tmp_path):
    build, _ = modules
    state, output = tmp_path / 'state', tmp_path / 'output'
    current, pending = 'a' * 40, 'b' * 40
    build.write_json(state / 'queue/current.json', {'commit': current, 'domestic': True})
    build.write_json(state / 'queue/next.json', {'commit': pending, 'domestic': True})
    log = tmp_path / 'build.log'
    log.write_text('Writing reproducible ZIP\nZIP: package.zip\nPreprocessing\n<script>unsafe</script>')
    record = {'state': 'running', 'stage': 'build', 'commit': current, 'profile': 'domestic',
              'started': build.now(), 'stage_started': build.now(), 'log': str(log)}
    build.update_status(state, {'output': str(output)}, record)
    details = build.status_details(state, record)
    assert [item['commit'] for item in details['queue']] == [pending]
    assert 'Inno Setup' in details['step']
    page = (output / 'build-status.html').read_text(encoding='utf-8')
    assert 'Очередь: 1' in page and pending[:12] in page
    assert 'новые сверху' in page
    assert page.index('&lt;script&gt;unsafe&lt;/script&gt;') < page.index('Preprocessing')
    assert 'Последняя запись' in page and 'На этапе:' in page
    assert '<script>unsafe</script>' not in page
    assert '&lt;script&gt;unsafe&lt;/script&gt;' in page
    log.write_text('Writing reproducible ZIP')
    build.update_status(state, {'output': str(output)}, record, render_only=True)
    assert 'Создание ZIP-архива' in (output / 'build-status.html').read_text(encoding='utf-8')
    assert json.loads((state / 'status.json').read_text()) == record


def test_build_scratch_is_scoped_to_configured_volume_and_not_system_temp(modules, tmp_path, monkeypatch):
    build, _ = modules
    system_temp = tmp_path / 'system-temp'
    monkeypatch.setenv('TEMP', str(system_temp))
    monkeypatch.setenv('PYTHONPATH', 'external-python')
    cache = tmp_path / 'build-data'
    env = build.build_environment({'cache': str(cache)}, 'run-123')
    expected = cache / 'temp/run-123'
    assert env['TEMP'] == env['TMP'] == env['TMPDIR'] == str(expected.resolve())
    assert expected.is_dir() and not system_temp.exists()
    assert 'PYTHONPATH' not in env
    assert build.os.environ['TEMP'] == str(system_temp)
    custom = tmp_path / 'custom'
    env = build.build_environment({'cache': str(cache), 'temp_root': str(custom)}, 'run-456')
    assert Path(env['TEMP']) == custom / 'run-456'


def test_build_cleanup_removes_owned_checkout_and_scratch_including_logs(modules, tmp_path):
    build, _ = modules
    run = tmp_path / 'runs/owned'
    source = run / 'source'
    scratch = tmp_path / 'temp/owned'
    for folder in (source, scratch):
        folder.mkdir(parents=True)
        (folder / 'garbage.log').write_text('temporary')
        (folder / 'small.txt').write_text('temporary')
    report = run / 'result.json'
    report.write_text('retained result')
    assert build.cleanup_run(tmp_path, source, scratch, run) == []
    assert not source.exists() and not scratch.exists()
    assert report.read_text() == 'retained result'


def test_idle_cleanup_removes_small_generated_logs_but_keeps_current_evidence(modules, repo):
    build, clean = modules
    state = build.state_dir(repo)
    old = state / 'runs' / ('a' * 12 + '-20261108T123456000000Z')
    current = state / 'runs' / ('b' * 12 + '-20261108T123457000000Z')
    for run in (old, current):
        (run / 'source').mkdir(parents=True)
        (run / 'source/tiny.txt').write_text('scratch')
        (run / 'build.log').write_text('build evidence')
    build.write_json(state / 'status.json', {'log': str(current / 'build.log')})
    state.joinpath('launcher-old.log').write_text('obsolete')
    repo.joinpath('generated.log').write_text('obsolete')
    repo.joinpath('.env.private.log').write_text('preserve')
    report = clean.plan(repo, {})
    clean.apply_plan(report)
    assert not (old / 'source').exists() and not (old / 'build.log').exists()
    assert (current / 'build.log').is_file()
    assert not state.joinpath('launcher-old.log').exists()
    assert not repo.joinpath('generated.log').exists()
    assert repo.joinpath('.env.private.log').is_file()


def test_cached_full_requests_are_distinct_from_legacy_full_requests(modules, tmp_path, monkeypatch):
    build, _ = modules
    state, sha = tmp_path / 'state', 'a' * 40
    build.write_json(state / 'queue' / (sha + '-domestic.json'), {'commit': sha, 'domestic': True})
    build.write_json(state / 'queue' / (sha + '-cached.json'), {'commit': sha, 'cached': True})
    profiles = []
    monkeypatch.setattr(build, 'run_build', lambda repo, state, config, commit:
                        profiles.append((config['domestic'], config['cached'])) or True)
    assert build.drain(tmp_path, state, {})
    assert set(profiles) == {(True, False), (False, True)}


def test_component_cache_cleanup_keeps_current_key_even_if_it_is_old(modules, repo, tmp_path):
    build, clean = modules
    cache = tmp_path / 'cache'
    keys = ['a' * 64, 'b' * 64, 'c' * 64]
    for index, key in enumerate(keys):
        folder = cache / 'component-bundles' / key
        folder.mkdir(parents=True)
        (folder / 'cache.json').write_text('{}')
        (folder / 'components.zip').write_bytes(b'fixture')
        os.utime(folder, (100 + index, 100 + index))
    build.write_json(build.state_dir(repo) / 'last-success.json', {'component_cache_key': keys[0]})
    report = clean.plan(repo, {'cache': str(cache)})
    clean.apply_plan(report)
    assert (cache / 'component-bundles' / keys[0]).is_dir()
    assert not (cache / 'component-bundles' / keys[1]).exists()
    assert (cache / 'component-bundles' / keys[2]).is_dir()


def test_owned_scratch_cleanup_removes_readonly_git_objects(modules, tmp_path):
    import stat
    build, _ = modules
    scratch = tmp_path / 'scratch'
    object_file = scratch / 'repo/.git/objects/ab/fixture'
    object_file.parent.mkdir(parents=True)
    object_file.write_bytes(b'git object')
    object_file.chmod(stat.S_IREAD)
    build.remove_tree(scratch, tmp_path)
    assert not scratch.exists()


def test_readonly_cleanup_never_escapes_its_boundary(modules, tmp_path):
    build, _ = modules
    outside = tmp_path / 'outside'
    outside.mkdir()
    sentinel = outside / 'keep.txt'
    sentinel.write_text('preserve')
    with pytest.raises(ValueError, match='boundary'):
        build.remove_tree(outside, tmp_path / 'owned')
    assert sentinel.read_text() == 'preserve'


def test_cleanup_removes_incomplete_component_cache(modules, repo, tmp_path):
    _, clean = modules
    cache = tmp_path / 'cache'
    incomplete = cache / 'component-bundles' / ('a' * 64)
    incomplete.mkdir(parents=True)
    (incomplete / 'components.zip').write_bytes(b'interrupted build')
    clean.apply_plan(clean.plan(repo, {'cache': str(cache)}))
    assert not incomplete.exists()
