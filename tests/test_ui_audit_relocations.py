"""Relocation evidence cannot silently exempt lost controls, handlers or endpoints."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ui_audit_relocations', ROOT / 'scripts/check-ui-audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_relocations_require_each_source_marker_and_original_api(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, 'ROOT', tmp_path)
    source = tmp_path / 'shell.js'
    source.write_text("stop.id='stop'; command(stop); fetch('/api/native/stop');", encoding='utf-8')
    review = {
        'dynamic_ids': {'stop': {'source': 'shell.js', 'required': ["stop.id='stop'"]}},
        'handler_relocations': {'stop.onclick': {'source': 'shell.js', 'required': ['command(stop)']}},
        'api_relocations': {'/api/native/stop': 'shell.js'},
    }
    failures = []
    assert audit.reviewed_relocations(review, failures) == ({'stop'}, {('stop', 'onclick')}, {'/api/native/stop'})
    assert failures == []
    source.write_text('different implementation', encoding='utf-8')
    failures = []
    assert audit.reviewed_relocations(review, failures) == (set(), set(), set())
    assert len(failures) == 3


def test_missing_or_empty_evidence_is_not_a_retirement(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, 'ROOT', tmp_path)
    failures = []
    review = {'dynamic_ids': {'stop': {'source': 'missing.js', 'required': []}}}
    assert audit.reviewed_relocations(review, failures) == (set(), set(), set())
    assert failures == ['Incomplete relocated contract stop: missing.js']
