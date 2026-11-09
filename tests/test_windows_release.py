import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from scripts import windows_release


@pytest.mark.parametrize('ref,version', [('refs/heads/main', '0.9.0'), ('refs/tags/v0.8.34', '0.9.0'),
                                      ('refs/tags/v0.9.0-rc1', '0.9.0'), ('refs/tags/vbad', 'bad')])
def test_release_requires_the_exact_version_tag(ref, version):
    with pytest.raises(ValueError, match='existing'):
        windows_release.validate_ref(ref, version)


def test_release_accepts_matching_tag():
    assert windows_release.validate_ref('refs/tags/v0.9.0', '0.9.0') == 'v0.9.0'


def test_prepare_commits_one_build_increment_and_tag_then_dispatches_once(tmp_path, monkeypatch):
    repo, remote = tmp_path / 'repo with spaces', tmp_path / 'remote.git'
    def git(*args, cwd=repo):
        return subprocess.check_output(['git', *map(str, args)], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
    git('init', '--bare', remote, cwd=tmp_path)
    repo.mkdir()
    git('init', '-b', 'main')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.invalid')
    git('config', 'commit.gpgsign', 'false')
    (repo / 'windows-app').mkdir()
    (repo / 'windows-app/release-inputs.json').write_text('{"version":"0.9.1"}')
    (repo / 'docs/releases').mkdir(parents=True)
    (repo / 'docs/releases/0.9.1.md').write_text('Next release')
    (repo / 'BUILD').write_text('1\n')
    git('add', '.')
    git('commit', '-m', 'Ready for release')
    git('remote', 'add', 'origin', remote)
    git('push', '-u', 'origin', 'main')
    monkeypatch.setattr(windows_release, 'ROOT', repo)
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    dispatch = Mock()
    monkeypatch.setattr(windows_release, 'gh', dispatch)
    windows_release.prepare()
    assert (repo / 'BUILD').read_text() == '2\n'
    assert git('show', 'v0.9.1:BUILD') == '2'
    assert git('show', 'main:BUILD', cwd=remote) == '2'
    dispatch.assert_called_once_with('workflow', 'run', 'windows-release.yml', '--ref', 'v0.9.1')
    with pytest.raises(ValueError, match='already exists'):
        windows_release.prepare()
    assert (repo / 'BUILD').read_text() == '2\n'
    assert dispatch.call_count == 1


@pytest.mark.parametrize('existing,corrupt', [(None, False), (True, False), (False, False), (None, True)])
def test_publication_checks_downloaded_bytes_before_exposing_draft(tmp_path, monkeypatch, existing, corrupt):
    monkeypatch.setattr(windows_release, 'ROOT', tmp_path)
    (tmp_path / 'BUILD').write_text('1\n')
    notes = tmp_path / 'docs/releases/0.9.0.md'
    notes.parent.mkdir(parents=True)
    notes.write_text('Release notes', encoding='utf-8')
    assets = tmp_path / 'accepted'
    assets.mkdir()
    names = ['VideoDescriptor-0.9.0-windows-x64-setup.exe', 'VideoDescriptor-0.9.0-windows-x64.zip',
             'SHA256SUMS.json', 'acceptance-provenance.json']
    for name in names:
        (assets / name).write_text(name)
    state = {'isDraft': existing, 'assets': [{'name': name} for name in names]} if existing is not None else None
    def run(args, **kwargs):
        if args[:3] == ['gh', 'release', 'view']:
            return Mock(returncode=0 if state else 1, stdout=json.dumps(state), stderr='release not found')
        return Mock(returncode=0)
    runner = Mock(side_effect=run)
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
            windows_release.publish(assets, 'v0.9.0', '0.9.0', 'commit')
    else:
        windows_release.publish(assets, 'v0.9.0', '0.9.0', 'commit')
    edits = [command for command in commands if command[:2] == ('release', 'edit')]
    assert bool(edits) == (not corrupt and existing is not False)
    assert runner.call_args_list[0].args[0][1].endswith('ci_artifacts.py')
    if existing is False:
        assert commands == [next(c for c in commands if c[:2] == ('release', 'download'))]


def test_native_workflow_has_one_tag_publisher_and_no_container_dependency():
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / '.github/workflows/windows-release.yml').read_text(encoding='utf-8'))
    assert workflow['on']['push'] == {'tags': ['v*.*.*']}
    assert workflow['jobs']['verify']['with'] == {'windows_only': True}
    assert workflow['jobs']['verify']['needs'] == 'version'
    assert workflow['jobs']['publish']['needs'] == 'verify'
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
