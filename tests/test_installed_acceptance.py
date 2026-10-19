"""Result-contract regressions; no mocks are reported as real acceptance."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installed_acceptance_api', ROOT / 'windows-app/sandbox/acceptance_api.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


def speech():
    return {'device': 'CPU', 'duration': 9.14, 'segments': [
        {'id': 's1', 'start': 0.0, 'end': 4.0, 'text': 'The train arrives at nine.'}]}


def test_cpu_inference_requires_real_text_and_bounded_timestamps():
    result = api.validate_speech(speech())
    assert result['device'] == 'CPU' and result['segments'] == 1
    assert result['text'] == 'The train arrives at nine.'


def test_prepare_poll_retries_a_stale_snapshot_instead_of_failing_or_passing():
    state = {'preparing': False, 'error': '', 'capabilities': {'CPU': {'ready': False}}}
    assert not api.preparation_complete(state)
    state['capabilities']['CPU']['ready'] = True
    assert api.preparation_complete(state)
    state['preparing'] = True
    assert not api.preparation_complete(state)
    state['preparing'] = False
    state['capabilities']['CPU']['ready'] = False
    state['error'] = 'Actual worker failure'
    assert api.preparation_complete(state)  # caller records the error as FAIL


@pytest.mark.parametrize('field,value', [('device', 'GPU'), ('segments', [])])
def test_wrong_device_and_empty_results_are_not_pass(field, value):
    result = speech()
    result[field] = value
    with pytest.raises(ValueError):
        api.validate_speech(result)


@pytest.mark.parametrize('row', [
    {'start': 0, 'end': -1, 'text': 'recognized'},
    {'start': 6, 'end': 4, 'text': 'recognized'},
    {'start': 0, 'end': 50, 'text': 'recognized'},
    {'start': 0, 'end': 4, 'text': '  '},
])
def test_invalid_timestamp_or_empty_text_is_not_synthetic_success(row):
    result = speech()
    result['segments'] = [row]
    with pytest.raises(ValueError):
        api.validate_speech(result)


def write(folder, name, value):
    (folder / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def test_saved_translation_requires_all_ids_and_no_errors(tmp_path):
    write(tmp_path, 'transcript.json', [{'id': 's1'}, {'id': 's2'}])
    write(tmp_path, 'translations.json', {'s1': 'Поезд прибудет в девять.'})
    with pytest.raises(ValueError, match='every transcript'):
        api.validate_saved(tmp_path)
    write(tmp_path, 'translations.json', {'s1': 'Поезд прибудет в девять.', 's2': 'Сохраните субтитры.'})
    assert api.validate_saved(tmp_path)['translated_segments'] == 2
    write(tmp_path, 'translation-errors.json', ['Model returned invalid output'])
    with pytest.raises(ValueError, match='has errors'):
        api.validate_saved(tmp_path)


def test_notes_requires_persisted_notes_chapters_and_report(tmp_path):
    write(tmp_path, 'transcript.json', [{'id': 's1'}])
    write(tmp_path, 'translations.json', {'s1': 'Проверочная запись.'})
    write(tmp_path, 'notes.json', {'notes': [{'title': 'Тест'}]})
    write(tmp_path, 'chapters.json', [])
    with pytest.raises(ValueError, match='missing'):
        api.validate_saved(tmp_path, notes=True)
    write(tmp_path, 'chapters.json', [{'title': 'Глава'}])
    (tmp_path / 'report.html').write_text('<html>Тест</html>', encoding='utf-8')
    assert api.validate_saved(tmp_path, notes=True)['notes'] == 1


def test_acceptance_refuses_nonlocal_services_before_transmitting():
    client = api.InstalledAPI.__new__(api.InstalledAPI)
    client.origin = 'http://127.0.0.1:8000'
    with pytest.raises(ValueError, match='loopback'):
        client.request('/api/generate', base='https://example.com')
