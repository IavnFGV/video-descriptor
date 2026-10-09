import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer

import requests

from video_descriptor.library import lecture_info, library_page
from video_descriptor.report import render
from video_descriptor.serve import RangeRequestHandler


def test_saved_title_is_shared_survives_refresh_and_appears_in_library(tmp_path):
    folder = tmp_path / "output" / "lecture"
    folder.mkdir(parents=True)
    video = tmp_path / "original.mp4"
    video.write_bytes(b"video")
    (folder / "manifest.json").write_text(json.dumps({"video": str(video), "start": 0, "duration": None}))
    (folder / "notes.json").write_text('{"notes":[],"sections":[]}')
    (folder / "transcript.json").write_text('[]')
    (folder / "frames.json").write_text('[]')
    render(folder, video, [], [])
    variant = folder / "auto"
    variant.mkdir()
    render(variant, video, [], [])
    server = ThreadingHTTPServer(("127.0.0.1", 0),
                                partial(RangeRequestHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        url = base + "/output/lecture/title.json"
        response = requests.post(url, json={"title": "Лекция AWS <test>"}, timeout=5)
        assert response.status_code == 200
        assert response.json()["display"] == "Лекция AWS <test> [original.mp4]"
        assert requests.get(base + "/output/lecture/auto/title.json", timeout=5).json() == response.json()
        render(folder, video, [], [])
        assert lecture_info(folder)["title"] == "Лекция AWS <test>"
        (folder / "report.html").write_text("old report")
        upgraded = requests.get(base + "/output/lecture/report.html", timeout=5)
        assert upgraded.status_code == 200
        assert 'id="lecture-title"' in upgraded.text
        assert "Лекция AWS &lt;test&gt;" in upgraded.content.decode("utf-8")
        page = requests.get(base + "/output/", timeout=5).text
        assert "Лекция AWS &lt;test&gt; [original.mp4]" in page
        assert "Лекция AWS <test>" not in page
        assert library_page(tmp_path / "output").count('<article>') == 1
        assert video.read_bytes() == b"video"
        assert requests.post(url, json={"title": "x" * 201}, timeout=5).status_code == 400
        assert requests.post(url, json={"title": "changed"}, headers={"Origin": "https://other.example"}, timeout=5).status_code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
