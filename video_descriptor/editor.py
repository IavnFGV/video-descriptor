"""Personal Markdown notes, stored independently of generated model artifacts."""

import hashlib
import os
import tempfile
import threading
from pathlib import Path

LOCK = threading.Lock()


class EditConflict(Exception):
    pass


def load_document(folder: Path) -> dict:
    personal = folder / "notes.user.md"
    if personal.is_symlink():
        raise ValueError("Личная заметка должна быть обычным файлом")
    path = personal if personal.exists() else folder / "editor-default.md"
    if not path.exists():
        path = folder / "notes.md"
    text = path.read_text(encoding="utf-8")
    return {"text": text, "revision": hashlib.sha256(text.encode()).hexdigest(),
            "personal": personal.exists()}


def save_document(folder: Path, text: str, revision: str) -> dict:
    with LOCK:
        if load_document(folder)["revision"] != revision:
            raise EditConflict("Файл изменён в другой вкладке. Скачайте свои правки и обновите страницу.")
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder,
                                         prefix=".notes-user-", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            temporary.replace(folder / "notes.user.md")
        finally:
            temporary.unlink(missing_ok=True)
        return load_document(folder)
