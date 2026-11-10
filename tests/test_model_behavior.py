"""Evaluator validators and reports; these tests do not claim real model quality."""
import argparse
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('model_evaluation', ROOT / 'scripts/evaluate_models.py')
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_behavior_cases_have_grounded_and_format_assertions():
    cases = json.loads((ROOT / 'tests/model-behavior/cases.json').read_text(encoding='utf-8'))
    assert len({case['id'] for case in cases}) == len(cases)
    for case in cases:
        assert case['segments'] and case['required_any']
        assert evaluation.material(case)
    with pytest.raises(ValueError, match='Missing expected fact'):
        evaluation.validate_answer(cases[-1], '[[s0001]]\nНечто.\n[[s0002]]\nДругое.')
    # Production marker contract permits an empty continuation after a merged sentence.
    evaluation.validate_answer(cases[-1], '[[s0001]]\nПоезд прибывает в девять.\n[[s0002]]\n')


def test_evaluation_reports_failures_without_retrying_until_green(tmp_path, monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {'models': [{'name': 'test', 'digest': 'identity'}]}

    monkeypatch.setattr(evaluation.requests, 'get', lambda *a, **kw: Response())
    calls = []

    def generate(*args, **kwargs):
        calls.append(args)
        return 'A malformed answer'

    monkeypatch.setattr(evaluation, 'chat_json', generate)
    cases = ROOT / 'tests/model-behavior/cases.json'
    assert evaluation.run(argparse.Namespace(base_url='http://127.0.0.1:1234', provider='ollama', model='test',
                          cases=cases, examples=None, output=tmp_path)) == 1
    report = json.loads((tmp_path / 'report.json').read_text(encoding='utf-8'))
    assert report['status'] == 'FAIL' and len(calls) == len(report['cases']) == 4
    assert all(row['prompt_sha256'] and row['case_sha256'] for row in report['cases'])
    events = [json.loads(line) for line in (tmp_path / 'application-events.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len([e for e in events if e['action'] == 'operation_started']) == 4
    assert len([e for e in events if e['action'] == 'operation_finished' and e['status'] == 'error']) == 4
    assert all(e.get('operation_id') and e.get('request_id') for e in events)
    assert 'A malformed answer' not in str(events)
