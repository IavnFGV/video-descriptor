import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from scripts import windows_release

NOTES = ('# Video Descriptor 0.9.1 — сборка 2\n'
         '\n'
         '## Что изменилось\n'
         '\n'
         '- Исправлена публикация артефактов под блокировкой на Windows.\n')
OTHER_NOTES = ('# Video Descriptor 0.9.1 — сборка 3\n'
               '\n'
               '## Что изменилось\n'
               '\n'
               '- Добавлен переход к участкам расшифровки без таймкодов.\n')


def git(*args, cwd=None):
    return subprocess.check_output(['git', *map(str, args)], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()


def git_blob(cwd, spec):
    return subprocess.check_output(['git', 'show', spec], cwd=cwd, stderr=subprocess.DEVNULL)


def make_repo(tmp_path, version='0.9.1', build='1'):
    """Temporary repository with a remote, a product version and a tracked BUILD."""
    repo, remote = tmp_path / 'repo with spaces', tmp_path / 'remote.git'
    git('init', '--bare', remote, cwd=tmp_path)
    repo.mkdir()
    git('init', '-b', 'main', cwd=repo)
    git('config', 'user.name', 'Test', cwd=repo)
    git('config', 'user.email', 'test@example.invalid', cwd=repo)
    git('config', 'commit.gpgsign', 'false', cwd=repo)
    (repo / 'windows-app').mkdir()
    (repo / 'windows-app/release-inputs.json').write_text(json.dumps({'version': version}))
    (repo / 'docs/releases').mkdir(parents=True)
    (repo / 'BUILD').write_text(build + '\n')
    git('add', '.', cwd=repo)
    git('commit', '-m', 'Ready for release', cwd=repo)
    git('remote', 'add', 'origin', remote, cwd=repo)
    git('push', '-u', 'origin', 'main', cwd=repo)
    return repo


def commit_notes(repo, text, message='Release notes for the next build'):
    (repo / 'docs/releases/next-build.md').write_text(text, encoding='utf-8')
    git('add', '.', cwd=repo)
    git('commit', '-m', message, cwd=repo)
    git('push', 'origin', 'main', cwd=repo)


def make_assets(repo, version, build=None):
    assets = repo / 'accepted'
    assets.mkdir(exist_ok=True)
    names = windows_release.artifact_names(version, build)
    for name in names:
        (assets / name).write_text(name)
    return assets, names


def github_runner(state, real_run):
    """Stub GitHub calls only; git and the artifact gate keep their real behaviour."""
    def run(args, **kwargs):
        if args[:3] == ['gh', 'release', 'view']:
            if state is None:
                return Mock(returncode=1, stdout='', stderr='release not found')
            return Mock(returncode=0, stdout=json.dumps(state), stderr='')
        if args and args[0] == 'gh':
            return Mock(returncode=0)
        if any('ci_artifacts.py' in str(item) for item in args):
            return Mock(returncode=0)
        return real_run(args, **kwargs)
    return run


@pytest.mark.parametrize('ref,version', [('refs/heads/main', '0.9.0'), ('refs/tags/v0.8.34', '0.9.0'),
                                      ('refs/tags/v0.9.0-rc1', '0.9.0'), ('refs/tags/vbad', 'bad')])
def test_release_requires_the_exact_version_tag(ref, version):
    with pytest.raises(ValueError, match='existing'):
        windows_release.validate_ref(ref, version)


def test_release_accepts_matching_tag():
    assert windows_release.validate_ref('refs/tags/v0.9.0', '0.9.0', 3) == 'v0.9.0'
    assert windows_release.validate_ref('refs/tags/v0.9.0-build.4', '0.9.0', 4) == 'v0.9.0-build.4'
    assert windows_release.validate_ref('refs/tags/v0.9.0-build.0012', '0.9.0', 12) == 'v0.9.0-build.0012'
    assert windows_release.validate_ref('refs/tags/v0.9.0-build.12', '0.9.0', 12) == 'v0.9.0-build.12'
    for ref in ['refs/tags/v0.9.0-build.3', 'refs/tags/v0.9.0-build.04', 'refs/tags/v0.9.1-build.4']:
        with pytest.raises(ValueError, match='existing'):
            windows_release.validate_ref(ref, '0.9.0', 4)


def test_prepare_build_12_uses_padded_identity(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, build='11')
    commit_notes(repo, NOTES)
    monkeypatch.setattr(windows_release, 'ROOT', repo)
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    dispatch = Mock()
    monkeypatch.setattr(windows_release, 'gh', dispatch)
    windows_release.prepare()
    assert (repo / 'BUILD').read_text() == '0012\n'
    assert git_blob(repo, 'v0.9.1-build.0012:docs/releases/0.9.1-build.0012.md') == NOTES.encode('utf-8')
    monkeypatch.setenv('GITHUB_REF', 'refs/tags/v0.9.1-build.0012')
    assert windows_release.validate()[0] == 'v0.9.1-build.0012'
    assert windows_release.artifact_names('0.9.1', '0012')[0] == 'VideoDescriptor-0.9.1-build.0012-windows-x64-setup.exe'
    dispatch.assert_called_once_with('workflow', 'run', 'windows-release.yml', '--ref', 'v0.9.1-build.0012')


def test_prepare_records_the_prepared_notes_with_the_build_tag(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    remote = tmp_path / 'remote.git'
    commit_notes(repo, NOTES)
    monkeypatch.setattr(windows_release, 'ROOT', repo)
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    dispatch = Mock()
    monkeypatch.setattr(windows_release, 'gh', dispatch)
    windows_release.prepare()
    assert (repo / 'BUILD').read_text() == '2\n'
    assert git_blob(repo, 'v0.9.1-build.2:docs/releases/0.9.1-build.2.md') == NOTES.encode('utf-8')
    assert git('show', 'main:docs/releases/0.9.1-build.2.md', cwd=remote) == NOTES.strip()
    # The prepared notes are consumed; the tagged commit keeps them under the build name.
    assert not (repo / 'docs/releases/next-build.md').exists()
    assert 'docs/releases/next-build.md' not in git('ls-tree', '-r', '--name-only', 'v0.9.1-build.2', cwd=repo)
    dispatch.assert_called_once_with('workflow', 'run', 'windows-release.yml', '--ref', 'v0.9.1-build.2')


def test_prepare_commits_one_build_increment_and_tag_then_dispatches_once(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    remote = tmp_path / 'remote.git'
    commit_notes(repo, NOTES)
    monkeypatch.setattr(windows_release, 'ROOT', repo)
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    dispatch = Mock()
    monkeypatch.setattr(windows_release, 'gh', dispatch)
    windows_release.prepare()
    assert (repo / 'BUILD').read_text() == '2\n'
    assert git('show', 'v0.9.1-build.2:BUILD', cwd=repo) == '2'
    assert git('show', 'main:BUILD', cwd=remote) == '2'
    dispatch.assert_called_once_with('workflow', 'run', 'windows-release.yml', '--ref', 'v0.9.1-build.2')
    monkeypatch.setenv('GITHUB_REF', 'refs/tags/v0.9.1-build.2')
    assert windows_release.validate()[0] == 'v0.9.1-build.2'
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    commit_notes(repo, OTHER_NOTES, 'Release notes for the following build')
    windows_release.prepare()  # A new explicit preparation builds the same product version again.
    assert (repo / 'BUILD').read_text() == '3\n'
    assert git('show', 'v0.9.1-build.2:BUILD', cwd=repo) == '2'
    assert git('show', 'v0.9.1-build.3:BUILD', cwd=repo) == '3'
    assert git_blob(repo, 'v0.9.1-build.3:docs/releases/0.9.1-build.3.md') == OTHER_NOTES.encode('utf-8')
    monkeypatch.setenv('GITHUB_REF', 'refs/tags/v0.9.1-build.3')
    assert windows_release.validate()[0] == 'v0.9.1-build.3'
    assert dispatch.call_count == 2
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    git('tag', 'v0.9.1-build.4', cwd=repo)
    with pytest.raises(ValueError, match='already exists'):
        windows_release.prepare()
    assert (repo / 'BUILD').read_text() == '3\n'
    assert dispatch.call_count == 2
    git('checkout', '--detach', 'HEAD', cwd=repo)
    git('commit', '--allow-empty', '-m', 'Newer main', cwd=repo)
    with pytest.raises(ValueError, match='main changed'):
        windows_release.prepare()
    assert dispatch.call_count == 2
    assert (repo / 'BUILD').read_text() == '3\n'


@pytest.mark.parametrize('content,message', [
    (None, 'Write docs/releases/next-build.md'),
    ('', 'not ready'),
    ('   \n', 'not ready'),
    ('# Video Descriptor\n\n- TODO: описать изменения.\n', 'not ready'),
    ('# Video Descriptor 0.9.1\n\n- TODO\n', 'not ready'),
    ('# Video Descriptor 0.9.1\n\n- short\n', 'not ready'),
    ('# Video Descriptor\n\n- описание.\n', 'not ready'),
])
def test_prepare_refuses_unfinished_release_notes(tmp_path, monkeypatch, content, message):
    repo = make_repo(tmp_path)
    if content is not None:
        (repo / 'docs/releases/next-build.md').write_text(content, encoding='utf-8')
        git('add', '.', cwd=repo)
        git('commit', '-m', 'Unfinished release notes', cwd=repo)
        git('push', 'origin', 'main', cwd=repo)
    monkeypatch.setattr(windows_release, 'ROOT', repo)
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    dispatch = Mock()
    monkeypatch.setattr(windows_release, 'gh', dispatch)
    with pytest.raises(ValueError, match=message):
        windows_release.prepare()
    assert (repo / 'BUILD').read_text() == '1\n'
    assert dispatch.call_count == 0
    assert git('tag', '--list', cwd=repo) == ''


def test_prepare_refuses_notes_repeated_from_the_previous_build(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    commit_notes(repo, NOTES)
    monkeypatch.setattr(windows_release, 'ROOT', repo)
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    dispatch = Mock()
    monkeypatch.setattr(windows_release, 'gh', dispatch)
    windows_release.prepare()
    commit_notes(repo, NOTES, 'The same notes again')
    with pytest.raises(ValueError, match='repeats the previous build'):
        windows_release.prepare()
    assert (repo / 'BUILD').read_text() == '2\n'
    assert dispatch.call_count == 1


def test_next_notes_writes_a_template_without_committing_anything(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, build='3')
    monkeypatch.setattr(windows_release, 'ROOT', repo)
    before = git('rev-parse', 'HEAD', cwd=repo)
    windows_release.next_notes()
    template = (repo / 'docs/releases/next-build.md').read_text(encoding='utf-8')
    assert 'NEXT-BUILD-PLACEHOLDER' in template
    assert '0.9.1' in template and '4' in template
    assert git('rev-parse', 'HEAD', cwd=repo) == before
    assert git('status', '--porcelain', '--untracked-files=all', cwd=repo) == '?? docs/releases/next-build.md'
    (repo / 'docs/releases/next-build.md').write_text(NOTES, encoding='utf-8')
    with pytest.raises(ValueError, match='already holds release notes'):
        windows_release.next_notes()
    assert (repo / 'docs/releases/next-build.md').read_text(encoding='utf-8') == NOTES


@pytest.mark.parametrize('qualified', [False, True])
@pytest.mark.parametrize('existing,corrupt', [(None, False), (True, False), (False, False), (None, True)])
def test_publication_checks_downloaded_bytes_before_exposing_draft(tmp_path, monkeypatch, existing, corrupt, qualified):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git('init', '-b', 'main', cwd=repo)
    git('config', 'user.name', 'Test', cwd=repo)
    git('config', 'user.email', 'test@example.invalid', cwd=repo)
    version, build = '0.9.0', 1
    tag = 'v0.9.0-build.1' if qualified else 'v0.9.0'
    notes = 'Release notes for this build.\n'
    path = f'docs/releases/{version}-build.{build}.md' if qualified else f'docs/releases/{version}.md'
    (repo / path).parent.mkdir(parents=True)
    (repo / path).write_text(notes, encoding='utf-8')
    (repo / 'BUILD').write_text('1\n')
    git('add', '.', cwd=repo)
    git('commit', '-m', 'Release', cwd=repo)
    git('tag', '-a', tag, '-m', tag, cwd=repo)
    monkeypatch.setattr(windows_release, 'ROOT', repo)
    assets, names = make_assets(repo, version, build if qualified else None)
    state = {'isDraft': existing, 'assets': [{'name': name} for name in names], 'body': notes} \
        if existing is not None else None
    real_run = subprocess.run
    runner = Mock(side_effect=github_runner(state, real_run))
    monkeypatch.setattr(windows_release.subprocess, 'run', runner)
    commands = []
    def gh(*args):
        commands.append(args)
        if args[:2] == ('release', 'download'):
            folder = Path(args[args.index('--dir') + 1])
            for name in names:
                shutil.copyfile(assets / name, folder / name)
            if corrupt:
                (folder / names[0]).write_text('corrupt')
    monkeypatch.setattr(windows_release, 'gh', gh)
    if corrupt:
        with pytest.raises(ValueError, match='differs'):
            windows_release.publish(assets, tag, version, 'commit')
    else:
        windows_release.publish(assets, tag, version, 'commit')
    edits = [command for command in commands if command[:2] == ('release', 'edit')]
    assert bool(edits) == (not corrupt and existing is not False)
    gate = runner.call_args_list[0].args[0]
    assert gate[1].endswith('ci_artifacts.py')
    assert ('--build-qualified' in gate) == qualified
    if existing is False:
        assert commands == [next(c for c in commands if c[:2] == ('release', 'download'))]


def test_publication_uses_the_notes_recorded_in_the_tagged_commit(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git('init', '-b', 'main', cwd=repo)
    git('config', 'user.name', 'Test', cwd=repo)
    git('config', 'user.email', 'test@example.invalid', cwd=repo)
    version, build = '0.9.0', 1
    (repo / 'docs/releases').mkdir(parents=True)
    (repo / 'docs/releases/0.9.0-build.1.md').write_text(NOTES, encoding='utf-8')
    (repo / 'docs/releases/0.9.0.md').write_text('Version notes of the release.\n', encoding='utf-8')
    (repo / 'BUILD').write_text('1\n')
    git('add', '.', cwd=repo)
    git('commit', '-m', 'Build notes', cwd=repo)
    git('tag', '-a', 'v0.9.0-build.1', '-m', 'build 1', cwd=repo)
    # A newer commit changes the version notes and prepares the next build.
    (repo / 'docs/releases/0.9.0.md').write_text('Rewritten version notes.\n', encoding='utf-8')
    (repo / 'docs/releases/next-build.md').write_text(OTHER_NOTES, encoding='utf-8')
    git('add', '.', cwd=repo)
    git('commit', '-m', 'Newer notes', cwd=repo)
    monkeypatch.setattr(windows_release, 'ROOT', repo)
    assets, names = make_assets(repo, version, build)
    used = []
    real_run = subprocess.run
    monkeypatch.setattr(windows_release.subprocess, 'run', Mock(side_effect=github_runner(None, real_run)))
    def gh(*args):
        if '--notes-file' in args:
            used.append(Path(args[args.index('--notes-file') + 1]).read_text(encoding='utf-8'))
        if args[:2] == ('release', 'download'):
            folder = Path(args[args.index('--dir') + 1])
            for name in names:
                shutil.copyfile(assets / name, folder / name)
    monkeypatch.setattr(windows_release, 'gh', gh)
    windows_release.publish(assets, 'v0.9.0-build.1', version, 'commit')
    assert used and set(used) == {NOTES}  # Notes of a newer commit never replace the tagged ones.


def test_publication_refuses_to_change_notes_of_a_published_release(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git('init', '-b', 'main', cwd=repo)
    git('config', 'user.name', 'Test', cwd=repo)
    git('config', 'user.email', 'test@example.invalid', cwd=repo)
    version, build = '0.9.0', 1
    (repo / 'docs/releases').mkdir(parents=True)
    (repo / 'docs/releases/0.9.0-build.1.md').write_text(NOTES, encoding='utf-8')
    (repo / 'BUILD').write_text('1\n')
    git('add', '.', cwd=repo)
    git('commit', '-m', 'Build notes', cwd=repo)
    git('tag', '-a', 'v0.9.0-build.1', '-m', 'build 1', cwd=repo)
    monkeypatch.setattr(windows_release, 'ROOT', repo)
    assets, names = make_assets(repo, version, build)
    state = {'isDraft': False, 'assets': [{'name': name} for name in names], 'body': 'Manually changed notes.'}
    real_run = subprocess.run
    monkeypatch.setattr(windows_release.subprocess, 'run', Mock(side_effect=github_runner(state, real_run)))
    commands = []
    def gh(*args):
        commands.append(args)
    monkeypatch.setattr(windows_release, 'gh', gh)
    with pytest.raises(ValueError, match='differ'):
        windows_release.publish(assets, 'v0.9.0-build.1', version, 'commit')
    assert commands == []


def test_publication_keeps_version_notes_for_legacy_tags(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git('init', '-b', 'main', cwd=repo)
    git('config', 'user.name', 'Test', cwd=repo)
    git('config', 'user.email', 'test@example.invalid', cwd=repo)
    version = '0.9.0'
    (repo / 'docs/releases').mkdir(parents=True)
    (repo / 'docs/releases/0.9.0.md').write_text(NOTES, encoding='utf-8')
    (repo / 'BUILD').write_text('1\n')
    git('add', '.', cwd=repo)
    git('commit', '-m', 'Version notes', cwd=repo)
    git('tag', '-a', 'v0.9.0', '-m', 'version', cwd=repo)
    monkeypatch.setattr(windows_release, 'ROOT', repo)
    assets, names = make_assets(repo, version)
    used = []
    real_run = subprocess.run
    monkeypatch.setattr(windows_release.subprocess, 'run', Mock(side_effect=github_runner(None, real_run)))
    def gh(*args):
        if '--notes-file' in args:
            used.append(Path(args[args.index('--notes-file') + 1]).read_text(encoding='utf-8'))
        if args[:2] == ('release', 'download'):
            folder = Path(args[args.index('--dir') + 1])
            for name in names:
                shutil.copyfile(assets / name, folder / name)
    monkeypatch.setattr(windows_release, 'gh', gh)
    windows_release.publish(assets, 'v0.9.0', version, 'commit')
    assert used and set(used) == {NOTES}


def test_release_flow_prepares_validates_and_publishes_one_build(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    commit_notes(repo, NOTES)
    monkeypatch.setattr(windows_release, 'ROOT', repo)
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    dispatch = Mock()
    monkeypatch.setattr(windows_release, 'gh', dispatch)
    windows_release.prepare()
    monkeypatch.setenv('GITHUB_REF', 'refs/tags/v0.9.1-build.2')
    tag, version, sha = windows_release.validate()
    assert (tag, version) == ('v0.9.1-build.2', '0.9.1')
    assets, names = make_assets(repo, version, 2)
    real_run = subprocess.run
    monkeypatch.setattr(windows_release.subprocess, 'run', Mock(side_effect=github_runner(None, real_run)))
    commands = []
    used = []
    def gh(*args):
        commands.append(args)
        if '--notes-file' in args:
            used.append(Path(args[args.index('--notes-file') + 1]).read_text(encoding='utf-8'))
        if args[:2] == ('release', 'download'):
            folder = Path(args[args.index('--dir') + 1])
            for name in names:
                shutil.copyfile(assets / name, folder / name)
    monkeypatch.setattr(windows_release, 'gh', gh)
    before = git('rev-parse', 'HEAD', cwd=repo)
    status = git('status', '--porcelain', cwd=repo)
    windows_release.publish(assets, tag, version, sha)
    creates = [command for command in commands if command[:2] == ('release', 'create')]
    assert creates and 'Video Descriptor 0.9.1 (build 2)' in creates[0]
    assert used and set(used) == {NOTES}
    assert any(command[:2] == ('release', 'edit') for command in commands)
    assert (repo / 'BUILD').read_text() == '2\n'
    # Publication changes neither the checkout nor the history.
    assert git('rev-parse', 'HEAD', cwd=repo) == before
    assert git('status', '--porcelain', cwd=repo) == status


def test_native_workflow_has_one_tag_publisher_and_no_container_dependency():
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / '.github/workflows/windows-release.yml').read_text(encoding='utf-8'))
    assert workflow['on']['push'] == {'tags': ['v*.*.*']}
    assert workflow['jobs']['verify']['with'] == {'windows_only': True}
    assert workflow['jobs']['verify']['needs'] == 'version'
    # A tag push skips prepare; explicit status checks must bridge that skipped ancestor.
    assert workflow['jobs']['verify']['if'] == "${{ !cancelled() && needs.version.result == 'success' }}"
    assert workflow['jobs']['publish']['needs'] == 'verify'
    assert workflow['jobs']['publish']['if'] == "${{ !cancelled() && needs.verify.result == 'success' }}"
    assert workflow['jobs']['publish']['permissions'] == {'contents': 'write', 'actions': 'read'}
    assert workflow['concurrency']['cancel-in-progress'] is False
    steps = workflow['jobs']['publish']['steps']
    gate = next(i for i, step in enumerate(steps) if 'ci_artifacts.py' in step.get('run', ''))
    publish = next(i for i, step in enumerate(steps) if 'windows_release.py publish' in step.get('run', ''))
    assert gate < publish
    old = yaml.safe_load((root / '.github/workflows/container-release.yml').read_text(encoding='utf-8'))
    assert 'push' not in old['on']
    full = yaml.safe_load((root / '.github/workflows/full-acceptance.yml').read_text(encoding='utf-8'))
    assert full['jobs']['container']['if'] == '${{ !inputs.windows_only }}'


def test_full_acceptance_and_publisher_use_build_qualified_artifacts():
    root = Path(__file__).resolve().parents[1]
    full = yaml.safe_load((root / '.github/workflows/full-acceptance.yml').read_text())
    steps = full['jobs']['windows']['steps']
    paths = next(step['run'] for step in steps if step.get('name') == 'Resolve versioned artifact paths')
    assert 'Get-Content BUILD' in paths and '-build.$build-windows-x64' in paths
    for step in steps:
        if any(script in step.get('run', '') for script in ('build_release.py', 'ci_artifacts.py')):
            assert '--build-qualified' in step['run']
    installer = (root / 'windows-app/installer.iss').read_text()
    builder = (root / 'windows-app/build_release.py').read_text()
    assert 'OutputBaseFilename={#ArtifactPrefix}-setup' in installer
    assert "f'/DArtifactPrefix={prefix}'" in builder
