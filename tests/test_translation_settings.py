import json
import sys

import pytest
import requests

from video_descriptor import gemini, translation_settings


@pytest.mark.parametrize('failure', [False, True])
@pytest.mark.parametrize('pinned', [False, True])
def test_translation_cli_uses_selected_model_and_fails_on_incomplete_result(tmp_path, monkeypatch, failure, pinned):
    from video_descriptor import translate

    folder = tmp_path / 'speech'
    folder.mkdir()
    (folder / 'transcript.json').write_text(json.dumps([
        {'id': 's1', 'start': 0, 'end': 5, 'text': 'Hello world'}]))
    args = ['translate', str(folder), '--model', 'fallback-model']
    if pinned:
        args += ['--local-model', 'pinned-model']
    monkeypatch.setattr(sys, 'argv', args)
    monkeypatch.setattr(translate, 'translation_settings', lambda: {'provider': 'ollama', 'ollama_model': 'selected-model'})
    monkeypatch.setattr(translate, 'refresh_reports', lambda *args: None)
    calls = []

    def generate(sources, model, base, log):
        calls.append(model)
        if failure:
            raise ValueError('Invalid translation')
        return {'s1': 'Привет, мир'}

    monkeypatch.setattr(translate, 'translate_resilient', generate)
    assert translate.main() == (1 if failure else 0)
    assert calls == ['pinned-model' if pinned else 'selected-model']
    errors = json.loads((folder / 'translation-errors.json').read_text())
    assert bool(errors) == failure


def test_refresh_translated_speech_only_report_does_not_require_video_frames(tmp_path):
    from video_descriptor import translate

    values = {'manifest.json': {'video': str(tmp_path / 'audio.wav')},
              'transcript.json': [{'id': 's1', 'start': 0, 'end': 5, 'text': 'Hello'}],
              'notes.json': {'notes': [], 'sections': []}, 'translations.json': {'s1': 'Привет'}}
    for name, value in values.items():
        (tmp_path / name).write_text(json.dumps(value), encoding='utf-8')
    translate.refresh_reports(tmp_path)
    assert 'Привет' in (tmp_path / 'report.html').read_text(encoding='utf-8')
    assert (tmp_path / 'ru.vtt').is_file()


def test_settings_keep_key_private_and_require_free_acknowledgement(tmp_path):
    result = translation_settings.save(tmp_path, {"provider": "gemini", "api_key": "secret"})
    assert result["has_key"] and "api_key" not in result
    assert translation_settings.load(tmp_path)["api_key"] == "secret"
    path = tmp_path / ".devcontainer" / "translation-settings.json"
    # Windows uses inherited NTFS ACLs rather than POSIX permission bits.
    import os
    if os.name != 'nt':
        assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="Подтвердите"):
        translation_settings.save(tmp_path, {"billing_mode": "free"})
    result = translation_settings.save(tmp_path, {"billing_mode": "free", "free_ack": True,
                                                  "api_key": ""})
    assert result["has_key"]
    assert translation_settings.load(tmp_path)["api_key"] == "secret"


def test_gemini_error_never_exposes_key(monkeypatch):
    class Response:
        ok = False
        status_code = 403
        text = "Rejected secret-api-key"
    monkeypatch.setattr(requests, "request", lambda *a, **kw: Response())
    with pytest.raises(gemini.GeminiServiceError) as exc:
        gemini.call("GET", "url", "secret-api-key")
    assert "secret-api-key" not in str(exc.value)


def test_cloud_translation_journal_contains_no_secret(monkeypatch, tmp_path):
    from video_descriptor.progress import ProgressLog
    data = {"candidates": [{"content": {"parts": [{"text": "[[s0001]]\nПривет"}]},
                            "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 50}}
    monkeypatch.setattr(gemini, "call", lambda *a, **kw: data)
    log = ProgressLog(lambda line: None, "file", tmp_path / "requests")
    answer = gemini.translate("Translate", "[[s0001]]\nHello",
                              {"model": "gemini-3.5-flash-lite", "api_key": "secret-key"}, log)
    assert answer == "[[s0001]]\nПривет"
    for path in tmp_path.rglob("*.json"):
        assert "secret-key" not in path.read_text()
    journal = next((tmp_path / "requests").iterdir())
    assert json.loads((journal / "result.json").read_text())["status"] == "complete"


def test_model_list_filters_non_translation_models_and_pages(monkeypatch):
    responses = iter([
        {"models": [{"name": "models/gemini-3.5-flash-lite",
                     "supportedGenerationMethods": ["generateContent"]}], "nextPageToken": "page"},
        {"models": [{"name": "models/gemini-image", "supportedGenerationMethods": ["generateContent"]}]},
    ])
    monkeypatch.setattr(gemini, "call", lambda *a, **kw: next(responses))
    assert [item["id"] for item in gemini.models("secret")] == ["gemini-3.5-flash-lite"]
