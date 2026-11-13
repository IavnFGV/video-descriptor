"""Project delegates remain bounded and free/paid choices stay explicit."""
import json
from pathlib import Path


def test_sol_architect_and_terra_worker_preserve_bounded_delegation():
    config = json.loads((Path(__file__).resolve().parents[1] / 'opencode.json').read_text(encoding='utf-8'))
    agents = config['agents']
    assert config['model'] == 'openai/gpt-6.1-sol'
    assert agents['executor']['model'] == 'openai/gpt-6.1-terra'
    assert agents['executor-free']['model'] == 'opencode/minimax-m3.1-flash-free#low'
    for name in ['executor', 'executor-free']:
        assert agents[name]['mode'] == 'subagent'
        assert agents[name]['steps'] == 1
        assert agents[name]['permissions'] == [{'action': '*', 'resource': '*', 'effect': 'deny'}]
        assert {'action': 'subagent', 'resource': name, 'effect': 'allow'} in agents['build']['permissions']
    assert agents['build']['permissions'][0] == {'action': 'subagent', 'resource': '*', 'effect': 'deny'}
    assert 'system' not in agents['build']  # Keep the built-in coding prompt.
