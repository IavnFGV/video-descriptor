"""Check the primary coding agent and the context-only advisor configuration."""
import json
from pathlib import Path

import pytest


@pytest.fixture
def config():
    return json.loads((Path(__file__).resolve().parents[1] / 'opencode.json').read_text(encoding='utf-8'))


def test_terra_is_primary_coding_agent(config):
    build = config['agents']['build']
    assert config['model'] == 'openai/gpt-6.1-terra'
    assert config['default_agent'] == 'build'
    assert build['model'] == 'openai/gpt-6.1-terra'
    assert 'steps' not in build
    assert 'system' not in build  # Keep the built-in coding prompt.
    assert build['permissions'] == [
        {'action': 'subagent', 'resource': '*', 'effect': 'deny'},
        {'action': 'subagent', 'resource': 'architecture-advisor', 'effect': 'allow'},
    ]
    assert set(config['agents']) == {'build', 'architecture-advisor'}


def test_sol_advisor_is_context_only_and_toolless(config):
    advisor = config['agents']['architecture-advisor']
    assert advisor['mode'] == 'subagent'
    assert advisor['model'] == 'openai/gpt-6.1-sol'
    assert advisor['permissions'] == [
        {'action': '*', 'resource': '*', 'effect': 'deny'},
    ]
    assert 'Use only the context and excerpts supplied' in advisor['system']
    assert 'cannot delegate' in advisor['system']
    assert 'cannot edit, validate, integrate, commit, push, or release' in advisor['system']
