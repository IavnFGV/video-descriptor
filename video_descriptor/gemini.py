"""Gemini text translation with secret-free request journals and live progress."""

import json
import time

import requests

from .progress import ProgressLog, update_status
from .request_log import RequestJournal

BASE = "https://generativelanguage.googleapis.com/v1beta"
RATES = {"gemini-3.5-flash-lite": (.30, 2.50), "gemini-3.1-flash-lite": (.25, 1.50),
         "gemini-3.8-flash": (.75, 3.75)}


class GeminiServiceError(requests.RequestException):
    """Service errors should stop a run rather than recursively split every block."""


def call(method, url, key, **kwargs):
    try:
        response = requests.request(method, url, headers={"x-goog-api-key": key},
                                    timeout=(10, 180), **kwargs)
    except requests.RequestException:
        raise GeminiServiceError("Gemini: ошибка соединения; готовые блоки сохранены") from None
    if not response.ok:
        raise GeminiServiceError(f"Gemini HTTP {response.status_code}: "
                                 f"{response.text.replace(key, '[REDACTED]')[:500]}")
    return response.json()


def models(key):
    if not key:
        raise ValueError("Сначала сохраните API-ключ")
    result, token = [], None
    while True:
        data = call("GET", BASE + "/models", key,
                    params={"pageSize": 100, **({"pageToken": token} if token else {})})
        for item in data.get("models", []):
            name = item["name"].removeprefix("models/")
            if (name.startswith("gemini-")
                    and "generateContent" in item.get("supportedGenerationMethods", [])
                    and not any(word in name for word in ("image", "tts", "live", "robotics"))):
                result.append({"id": name, "title": item.get("displayName", name),
                               "rates": RATES.get(name), 'input_tokens': item.get('inputTokenLimit'),
                               'output_tokens': item.get('outputTokenLimit')})
        token = data.get("nextPageToken")
        if not token:
            return result


def translate(prompt, text, settings, log=None):
    from .prompt_settings import effective
    prompt = effective('translate', prompt, log)
    model = settings["model"]
    config = {"temperature": 0, "maxOutputTokens": 4096, "responseMimeType": "text/plain"}
    if model == "gemini-3.5-flash-lite":
        config["thinkingConfig"] = {"thinkingLevel": "minimal"}
    elif model == "gemini-3.8-flash":
        config["thinkingConfig"] = {"thinkingLevel": "low"}
    payload = {"systemInstruction": {"parts": [{"text": prompt}]},
               "contents": [{"role": "user", "parts": [{"text": text}]}],
               "generationConfig": config}
    journal = None
    started = time.monotonic()
    if isinstance(log, ProgressLog):
        log.begin_request("translate", model, len(prompt) + len(text),
                          len(json.dumps(payload).encode()), 0, 4096)
        log.update(provider="gemini", request_thinking=False)
        if log.journal_dir:
            journal = RequestJournal(log.journal_dir, BASE + f"/models/{model}:generateContent",
                                     {"model": model, **payload}, log.snapshot(), "translate")
            update_status(log, request_log=str(journal.folder))
    if log:
        log(f"Gemini: перевод через {model}; отправляем только текст")
    try:
        data = call("POST", BASE + f"/models/{model}:generateContent", settings["api_key"],
                    json=payload)
        candidate = (data.get("candidates") or [{}])[0]
        answer = "".join(part.get("text", "") for part in
                         candidate.get("content", {}).get("parts", []) if not part.get("thought"))
        usage = data.get("usageMetadata", {})
        incoming = usage.get("promptTokenCount", 0)
        outgoing = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
        price = RATES.get(model)
        cost = (incoming * price[0] + outgoing * price[1]) / 1e6 if price else None
        update_status(log, received=len(answer), input_tokens=incoming, output_tokens=outgoing,
                      request_seconds=round(time.monotonic() - started, 2),
                      request_state="готово", estimated_usd=cost, request_started=None)
        if journal:
            event = {"message": {"content": answer}, "done": True}
            journal.raw(json.dumps(event, ensure_ascii=False).encode())
            journal.event(event)
            journal.write("gemini-response.json", data)
            journal.finish("complete")
            journal = None
        if candidate.get("finishReason") == "MAX_TOKENS":
            raise ValueError("Gemini: ответ достиг лимита; делим блок")
        if not answer.strip():
            raise GeminiServiceError("Gemini не вернул текст; проверьте журнал ответа")
        if log:
            log(f"Gemini: перевод готов, {incoming}/{outgoing} токенов, "
                + (f"оценка ${cost:.6f}" if cost is not None else "тариф модели не задан"))
        return answer
    except BaseException as exc:
        if journal:
            journal.finish("error", str(exc))
        update_status(log, request_started=None, request_state="ошибка Gemini")
        raise
