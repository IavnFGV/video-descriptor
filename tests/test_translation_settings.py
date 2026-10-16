import json

import pytest
import requests

from video_descriptor import gemini, translation_settings


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
