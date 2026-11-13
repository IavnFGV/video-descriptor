"""Committed agents are locked down; task grants must never become standing access."""
import json
from pathlib import Path

import pytest


@pytest.fixture
def config():
    return json.loads((Path(__file__).resolve().parents[1] / 'opencode.json').read_text(encoding='utf-8'))


def test_sol_architect_and_terra_worker_preserve_bounded_delegation(config):
    agents = config['agents']
    assert config['model'] == 'openai/gpt-6.1-sol'
    assert agents['executor']['model'] == 'openai/gpt-6.1-terra'
    assert agents['executor-free']['model'] == 'opencode/minimax-m3.1-flash-free#low'
    for name in ['executor', 'executor-free']:
        assert agents[name]['mode'] == 'subagent'
        assert {'action': 'subagent', 'resource': name, 'effect': 'allow'} in agents['build']['permissions']
    assert agents['build']['permissions'][0] == {'action': 'subagent', 'resource': '*', 'effect': 'deny'}
    assert 'system' not in agents['build']  # Keep the built-in coding prompt.


def test_terra_has_working_steps_but_no_model_variant_override(config):
    worker = config['agents']['executor']
    assert worker['steps'] == 8  # The last step is a terminal report, not a tool step.
    assert worker['model'] == 'openai/gpt-6.1-terra'
    assert 'request' not in worker


@pytest.mark.parametrize('name', ['executor', 'executor-free'])
def test_committed_workers_have_no_persistent_task_grants(config, name):
    # Exact equality catches stale path exceptions, wildcards and later allow rules.
    assert config['agents'][name]['permissions'] == [
        {'action': '*', 'resource': '*', 'effect': 'deny'},
    ]


def test_terra_prompt_retains_review_and_host_safety_boundaries(config):
    prompt = config['agents']['executor']['system']
    assert 'task-specific permissions' in prompt
    assert 'without grants, report BLOCKED' in prompt
    assert 'Never bypass or retry a denied action' in prompt
    assert 'Never change permissions, agent instructions or OpenCode configuration; Sol owns these' in prompt
    assert 'Sol owns architecture, validation commands, review, integration and commits' in prompt
    assert 'No shell, network, external directories, further delegation' in prompt
    assert 'not approval to merge, push or release' in prompt
    assert 'You have no tools or filesystem access' not in prompt


def test_free_worker_remains_explicitly_free_and_proposal_only(config):
    worker = config['agents']['executor-free']
    assert worker['steps'] == 1
    assert worker['model'] == 'opencode/minimax-m3.1-flash-free#low'
    assert 'You have no tools or filesystem access' in worker['system']
