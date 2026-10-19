"""Local translation preferences; secrets never appear in public responses."""

import base64
import json
import os
import re
import threading
from pathlib import Path

_SAVE_LOCK = threading.RLock()


def protected_key(data, *, decrypt=False):
    """Windows current-user DPAPI; no machine-wide key or plaintext fallback."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    outgoing = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise ValueError('Не удалось открыть/сохранить ключ Windows. Используйте ту же учётную запись Windows.')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(outgoing.data)


def load(root=None):
    root = Path(root or Path.cwd())
    path = root / ".devcontainer" / "translation-settings.json"
    value = {"provider": "ollama", "ollama_model": "", "model": "gemini-3.5-flash-lite",
             "billing_mode": "paid", "free_ack": False, "api_key": ""}
    if path.exists():
        value.update(json.loads(path.read_text(encoding='utf-8')))
        if value.get('api_key_dpapi'):
            if os.name != 'nt':
                raise ValueError('Ключ защищён учётной записью Windows; введите ключ на этом компьютере')
            value['api_key'] = protected_key(base64.b64decode(value['api_key_dpapi']), decrypt=True).decode('utf-8')
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
    with _SAVE_LOCK:
        return _save(root, changes)


def _save(root, changes):
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
    stored = dict(value)
    if os.name == 'nt' and value['api_key']:
        try:
            stored['api_key_dpapi'] = base64.b64encode(protected_key(value['api_key'].encode('utf-8'))).decode('ascii')
            stored['api_key'] = ''
        except BaseException:
            os.close(fd)
            temporary.unlink(missing_ok=True)
            raise
    with os.fdopen(fd, "w", encoding='utf-8') as stream:
        json.dump(stored, stream, ensure_ascii=False, indent=2)
    temporary.replace(path)
    return public(value)
