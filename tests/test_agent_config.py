"""Project delegates remain bounded and free/paid choices stay explicit."""
import json
from pathlib import Path


def test_separate_free_executor_preserves_working_paid_profile():
    config = json.loads((Path(__file__).resolve().parents[1] / 'opencode.json').read_text(encoding='utf-8'))
    agents = config['agents']
    assert agents['executor']['model'] == 'openrouter/deepseek/deepseek-v4.1-flash-1017#none'
    assert agents['executor-free']['model'] == 'opencode/minimax-m3.1-flash-free#low'
    for name in ['executor', 'executor-free']:
        assert agents[name]['mode'] == 'subagent'
        assert agents[name]['steps'] == 1
        assert agents[name]['permissions'] == [{'action': '*', 'resource': '*', 'effect': 'deny'}]
        assert {'action': 'subagent', 'resource': name, 'effect': 'allow'} in agents['build']['permissions']
