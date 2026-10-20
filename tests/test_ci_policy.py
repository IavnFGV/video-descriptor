"""Event/path/cancellation/release safety contracts; never execute heavy CI in tests."""
import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ci_changes', ROOT / 'scripts/ci_changes.py')
changes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changes)


def workflow(name):
    data = yaml.safe_load((ROOT / '.github/workflows' / name).read_text(encoding='utf-8'))
    data['on'] = data.get('on', data.get(True))  # YAML 1.1 vs GitHub YAML 1.2
    return data


@pytest.mark.parametrize('paths,expected', [
    (['README.md', 'docs/example.md'], (False, False, False, False)),
    (['video_descriptor/assets/create.css'], (True, True, False, False)),
    (['video_descriptor/assets/studio.js'], (True, True, False, False)),
    (['video_descriptor/serve.py'], (True, True, False, True)),
    (['Dockerfile'], (True, False, False, True)),
    (['compose.yaml'], (True, False, False, True)),
    (['windows-app/installer.iss'], (True, True, True, False)),
    (['windows-app/requirements-release.txt'], (True, True, True, False)),
    (['.github/workflows/full-acceptance.yml'], (True, False, False, False)),
    (['.github/workflows/windows-smoke.yml'], (True, True, False, False)),
    (['tests/test_jobs.py'], (True, False, False, False)),
])
def test_event_matrix(paths, expected):
    assert tuple(changes.classify(paths).values()) == expected


def test_exactly_one_automatic_pr_entrypoint_and_no_feature_push_duplicate():
    workflows = [workflow(p.name) for p in (ROOT / '.github/workflows').glob('*.yml')]
    automatic = [w for w in workflows if 'pull_request' in w['on']]
    assert len(automatic) == 1
    ci = automatic[0]
    assert ci['on']['push'] == {'branches': ['main']}
    assert 'synchronize' in ci['on']['pull_request']['types']
    assert all('workflow_run' not in w['on'] and 'pull_request_target' not in w['on'] for w in workflows)


def test_required_gate_runs_for_docs_and_propagates_conditional_failures():
    ci = workflow('ci.yml')
    assert 'paths' not in ci['on']['pull_request']
    gate = ci['jobs']['required']
    assert gate['if'] == 'always()'
    assert set(gate['needs']) == set(ci['jobs']) - {'required'}
    assert '"success","skipped"' in gate['steps'][0]['run']


def test_cancellation_scopes_pr_and_preserves_main_and_manual_release():
    group = workflow('ci.yml')['concurrency']
    assert 'github.workflow' in group['group']
    assert 'github.event.pull_request.number || github.sha' in group['group']
    assert group['cancel-in-progress'] == "${{ github.event_name == 'pull_request' }}"
    for name in ['full-acceptance.yml', 'container-release.yml']:
        policy = workflow(name)['concurrency']
        assert policy['cancel-in-progress'] is False
        assert 'github.run_id' in policy['group']


def test_heavy_acceptance_is_opt_in_and_release_tests_existing_assets():
    full = workflow('full-acceptance.yml')
    assert set(full['on']) == {'workflow_dispatch', 'workflow_call', 'release'}
    steps = full['jobs']['windows']['steps']
    builds = [s for s in steps if 'build_release.py' in s.get('run', '')]
    assert builds and all(s['if'] == "github.event_name != 'release'" for s in builds)
    assert any('gh release download' in s.get('run', '') for s in steps)
    assert sum('verify_installed.py' in s.get('run', '') for s in steps) == 1
    assert '--with-ollama' in next(s['run'] for s in steps if 'verify_installed.py' in s.get('run', ''))


def test_fast_and_smoke_have_no_models_or_full_lifecycle():
    ci = workflow('ci.yml')
    for job in ci['jobs'].values():
        if 'uses' not in job:
            assert not any(word in str(job) for word in ['build_release.py', 'verify_installed.py', 'Prepare-TestOllama'])
    smoke = workflow('windows-smoke.yml')['jobs']['smoke']['steps']
    assert sum('build_release.py' in s.get('run', '') for s in smoke) == 1
    assert all(word not in str(smoke) for word in ['prepare_test_model.py', 'Prepare-TestOllama', '--with-ollama'])
    assert all('--installer' not in s.get('run', '') for s in smoke if 'verify_release.py' in s.get('run', ''))
    assert 'inputs.installer' == next(s['if'] for s in smoke if 'check-installer-smoke.py' in s.get('run', ''))
    # Add-Type -OutputType WindowsApplication is unsupported in PowerShell Core.
    sdk = next(s for s in smoke if s.get('name') == 'Desktop SDK')
    assert sdk['run'].startswith('powershell -NoProfile -File ')


def test_pr_routing_uses_merge_base_and_accounts_for_renames(monkeypatch):
    commands = []
    def output(command, **kwargs):
        commands.append(command)
        return 'common-base\n' if command[1] == 'merge-base' else b'windows-app/app.py\0docs/moved.md\0'
    monkeypatch.setattr(changes.subprocess, 'check_output', output)
    assert changes.classify(changes.changed('main', 'head', True))['windows']
    assert commands[1][-2:] == ['common-base', 'head']
    assert '--no-renames' in commands[1]


@pytest.mark.parametrize('corruption', ['bytes', 'revision', 'provenance'])
def test_release_rejects_artifact_or_revision_substitution(tmp_path, monkeypatch, corruption):
    spec = importlib.util.spec_from_file_location('ci_artifacts', ROOT / 'scripts/ci_artifacts.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *a, **kw: 'accepted-sha\n')
    (tmp_path / 'windows-app').mkdir()
    (tmp_path / 'windows-app/release-inputs.json').write_text('{"version":"0.7.0"}')
    dist = tmp_path / 'dist'
    dist.mkdir()
    archive = dist / 'VideoDescriptor-0.7.0-windows-x64.zip'
    with zipfile.ZipFile(archive, 'w') as package:
        package.writestr('release-manifest.json', '{"version":"0.7.0"}')
    installer = dist / 'VideoDescriptor-0.7.0-windows-x64-setup.exe'
    installer.write_bytes(b'unit fixture, never executable')
    entries = [{'file': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in [archive, installer]]
    (dist / 'SHA256SUMS.json').write_text(json.dumps(entries))
    monkeypatch.setattr(sys, 'argv', ['ci_artifacts.py', '--record'])
    module.main()
    monkeypatch.setattr(sys, 'argv', ['ci_artifacts.py'])
    if corruption == 'bytes':
        installer.write_bytes(b'different artifact')
    elif corruption == 'revision':
        monkeypatch.setattr(module.subprocess, 'check_output', lambda *a, **kw: 'different-sha\n')
    else:
        (dist / 'acceptance-provenance.json').write_text('{"git_sha":"accepted-sha","artifacts":[]}')
    with pytest.raises(AssertionError):
        module.main()



def test_windows_workflows_resolve_artifact_names_from_release_inputs():
    for name in ('windows-smoke.yml', 'full-acceptance.yml'):
        source = (ROOT / '.github/workflows' / name).read_text()
        assert 'VideoDescriptor-0.7.0' not in source and 'VideoDescriptor-0.8.0' not in source
        assert 'Resolve versioned artifact paths' in source
        assert 'release-inputs.json' in source and '$env:VD_ZIP' in source and '$env:VD_INSTALLER' in source
