import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer

import pytest
import requests

from video_descriptor.editor import EditConflict, load_document, save_document
from video_descriptor.models import Source
from video_descriptor.report import render
from video_descriptor.serve import RangeRequestHandler


def test_personal_markdown_survives_report_regeneration_and_stale_save(tmp_path):
    speech = [Source(id="s1", start=0, end=1, text="hello")]
    render(tmp_path, tmp_path / "video.mp4", speech, [])
    initial = load_document(tmp_path)
    text = "## [00:00:30] Моя тема\n\n- Моя правка\n"
    saved = save_document(tmp_path, text, initial["revision"])
    assert saved["personal"]
    assert saved["text"] == text
    render(tmp_path, tmp_path / "video.mp4", speech, [])
    assert load_document(tmp_path) == saved
    with pytest.raises(EditConflict):
        save_document(tmp_path, "lost update", initial["revision"])
    assert (tmp_path / "notes.user.md").read_text() == text


def test_editor_api_saves_unicode_rejects_stale_revision_and_other_origin(tmp_path):
    folder = tmp_path / "output" / "lecture"
    folder.mkdir(parents=True)
    (folder / "report.html").write_text("report")
    (folder / "editor-default.md").write_text("## [00:00:00] Model")
    (folder / "notes.json").write_text('{"notes":[]}')
    server = ThreadingHTTPServer(("127.0.0.1", 0),
                                partial(RangeRequestHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/output/lecture/editor.json"
    try:
        initial = requests.get(url, timeout=5).json()
        payload = {"text": "## [00:01:00] Новый раздел\n\nОтвет **C**", "revision": initial["revision"]}
        response = requests.post(url, json=payload, timeout=5)
        assert response.status_code == 200
        assert requests.get(url, timeout=5).json()["text"] == payload["text"]
        assert json.loads((folder / "notes.json").read_text()) == {"notes": []}
        assert requests.post(url, json=payload, timeout=5).status_code == 409
        assert requests.post(url, json=payload, headers={"Origin": "https://other.example"},
                             timeout=5).status_code == 403
        outside = url.replace("/output/lecture/", "/")
        assert requests.post(outside, json=payload, timeout=5).status_code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
