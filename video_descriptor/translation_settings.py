"""Local translation preferences; secrets never appear in public responses."""

import json
import os
import re
from pathlib import Path


def load(root=None):
    root = Path(root or Path.cwd())
    path = root / ".devcontainer" / "translation-settings.json"
    value = {"provider": "ollama", "ollama_model": "", "model": "gemini-3.5-flash-lite",
             "billing_mode": "paid", "free_ack": False, "api_key": ""}
    if path.exists():
        value.update(json.loads(path.read_text()))
    if not value["api_key"]:
        value["api_key"] = os.getenv("GEMINI_API_KEY", "")
        env = root / ".env.gemini"
        if not value["api_key"] and env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    value["api_key"] = line.partition("=")[2].strip().strip("\"'")
    return value


def public(value):
    return {**{key: value[key] for key in ("provider", "model", "ollama_model", "billing_mode", "free_ack")},
            "has_key": bool(value["api_key"])}


def save(root, changes):
    value = load(root)
    for name in ("provider", "model", "ollama_model", "billing_mode", "free_ack", "api_key"):
        if name in changes and not (name == "api_key" and changes[name] == ""):
            value[name] = changes[name]
    if value["provider"] not in {"ollama", "gemini"}:
        raise ValueError("Неизвестный исполнитель перевода")
    if (not isinstance(value["model"], str)
            or not re.fullmatch(r"gemini-[a-zA-Z0-9.-]{1,100}", value["model"])):
        raise ValueError("Выберите Gemini-модель из списка")
    if not isinstance(value['ollama_model'], str) or (value['ollama_model'] and not re.fullmatch(r'[A-Za-z0-9._:/-]{1,150}', value['ollama_model'])):
        raise ValueError('Укажите название локальной модели перевода')
    if value["billing_mode"] not in {"paid", "free"} or type(value["free_ack"]) is not bool:
        raise ValueError("Некорректный режим оплаты")
    if not isinstance(value["api_key"], str) or len(value["api_key"]) > 512:
        raise ValueError("Некорректный API-ключ")
    if value["provider"] == "gemini":
        if not value["api_key"].strip():
            raise ValueError("Добавьте API-ключ Gemini")
        if value["billing_mode"] == "free" and not value["free_ack"]:
            raise ValueError("Подтвердите условия использования бесплатного проекта")
    path = Path(root) / ".devcontainer" / "translation-settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    temporary.replace(path)
    return public(value)
