"""Gemini text translation with secret-free request journals and live progress."""

import json
import random
import time

import requests

from .progress import ProgressLog, update_status
from .request_log import RequestJournal

BASE = "https://generativelanguage.googleapis.com/v1beta"
RATES = {"gemini-3.5-flash-lite": (.30, 2.50), "gemini-3.1-flash-lite": (.25, 1.50),
         "gemini-3.8-flash": (.75, 3.75)}
RETRY_DELAYS = (15, 30)


class GeminiServiceError(requests.RequestException):
    """Service errors should stop a run rather than recursively split every block."""

    def __init__(self, message, *, http_status=None):
        super().__init__(message)
        self.http_status = http_status


def call(method, url, key, *, log=None, journal=None, **kwargs):
    delays = RETRY_DELAYS if method == "POST" and url.endswith(":generateContent") else ()
    for attempt in range(1, len(delays) + 2):
        try:
            response = requests.request(method, url, headers={"x-goog-api-key": key},
                                        timeout=(10, 180), **kwargs)
        except requests.RequestException:
            raise GeminiServiceError("Gemini: ошибка соединения; готовые блоки сохранены") from None
        if response.ok:
            return response.json()
        code = response.status_code
        if code == 503 and attempt <= len(delays):
            delay = delays[attempt - 1] + random.randint(0, 3)
            label = f"попытка {attempt + 1}/{len(delays) + 1}"
            if journal:
                journal.retry(attempt + 1, code=code)
            if log:
                update_status(log, request_state=f"Gemini HTTP 503: {label} через {delay} сек")
                log(f"Gemini временно недоступна (HTTP 503); {label} через {delay} сек")
            time.sleep(delay)
            if log:
                update_status(log, request_state=f"ожидание ответа ({label})")
                log(f"Gemini: повторно отправляем тот же запрос ({label})")
            continue
        if code == 503:
            message = "сервис временно недоступен"
            if attempt > 1:
                message += f" после {attempt - 1} повторов"
            message += "; попробуйте позже"
        elif code == 429:
            message = "достигнут лимит запросов или квота проекта; проверьте лимиты в Google AI Studio"
        elif code in (401, 403):
            message = "нет доступа; проверьте API-ключ и права проекта"
        else:
            message = "сервис отклонил запрос; проверьте модель и параметры запроса" if code < 500 else "ошибка сервиса"
        raise GeminiServiceError(f"Gemini HTTP {code}: {message}", http_status=code)


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


def translate(prompt, text, settings, log=None, *, output_tokens=4096, task='translate', schema=None, images=None, effective_prompt=False):
    from .prompt_settings import effective
    if not effective_prompt:
        prompt = effective(task, prompt, log)
    model = settings["model"]
    config = {"temperature": 0, "maxOutputTokens": output_tokens, "responseMimeType": "text/plain"}
    if model == "gemini-3.5-flash-lite":
        config["thinkingConfig"] = {"thinkingLevel": "minimal"}
    elif model == "gemini-3.8-flash":
        config["thinkingConfig"] = {"thinkingLevel": "low"}
    payload = {"systemInstruction": {"parts": [{"text": prompt}]},
               "contents": [{"role": "user", "parts": [{"text": text}]}],
               "generationConfig": config}
    if schema is not None:
        payload['generationConfig'].update(responseMimeType='application/json', responseJsonSchema=schema)
    if images:
        payload['contents'][0]['parts'].extend({'inlineData': {'mimeType': 'image/jpeg', 'data': image}} for image in images)
    journal = None
    started = time.monotonic()
    if isinstance(log, ProgressLog):
        log.begin_request(task, model, len(prompt) + len(text),
                          len(json.dumps(payload).encode()), len(images or []), output_tokens)
        log.update(provider="gemini", request_thinking=False)
        if log.journal_dir:
            journal = RequestJournal(log.journal_dir, BASE + f"/models/{model}:generateContent",
                                     {"model": model, **payload}, log.snapshot(), task)
            update_status(log, request_log=str(journal.folder))
    if log:
        log(f"Gemini: {task} через {model}; отправляем " + ("текст и выбранные изображения" if images else "только текст"))
    try:
        data = call("POST", BASE + f"/models/{model}:generateContent", settings["api_key"],
                    json=payload, log=log, journal=journal)
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
            journal.finish("error", str(exc), code=getattr(exc, "http_status", None))
        update_status(log, request_started=None, request_state="ошибка Gemini")
        raise
