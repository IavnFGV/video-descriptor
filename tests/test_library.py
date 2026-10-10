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
        redirect = requests.get(base + "/output/lecture/report.html", allow_redirects=False, timeout=5)
        assert redirect.status_code == 302
        assert redirect.headers["Location"] == "/create?folder=lecture&stage=notes"
        upgraded = requests.get(base + "/output/lecture/report.html?embedded=1", timeout=5)
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


def test_unfinished_record_opens_workspace_instead_of_folder_listing(tmp_path):
    folder = tmp_path / "output" / "unfinished"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"video": "recording.mp4"}))
    page = library_page(tmp_path / "output")
    assert 'href="/create?folder=unfinished"' in page
    assert 'href="/output/unfinished/"' not in page
    assert "/speech" not in page


def test_speech_only_report_is_not_advertised_as_ready_notes(tmp_path):
    folder = tmp_path / "output" / "speech-only"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"video": "recording.wav"}))
    (folder / "speech.json").write_text('{}')
    (folder / "report.html").write_text('legacy speech report')
    page = library_page(tmp_path / "output")
    assert "Конспект ещё не создан" in page
    assert "Читать конспект" not in page
    assert 'href="/create?folder=speech-only"' in page


def test_nested_report_opens_notes_variant_in_workspace(tmp_path):
    folder = tmp_path / 'output' / 'lecture'
    variant = folder / 'auto'
    variant.mkdir(parents=True)
    (folder / 'manifest.json').write_text(json.dumps({'video': str(tmp_path / 'video.mp4')}))
    (folder / 'notes.json').write_text('{"notes":[],"sections":[]}')
    (folder / 'transcript.json').write_text('[]')
    (folder / 'frames.json').write_text('[]')
    render(folder, tmp_path / 'video.mp4', [], [])
    render(variant, tmp_path / 'video.mp4', [], [])
    server = ThreadingHTTPServer(('127.0.0.1', 0),
                                partial(RangeRequestHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        response = requests.get(base + '/output/lecture/auto/report.html', allow_redirects=False, timeout=5)
        assert response.status_code == 302
        assert response.headers['Location'] == '/create?folder=lecture&stage=notes&report=auto'
        embedded = requests.get(base + '/output/lecture/auto/report.html?embedded=1', timeout=5)
        assert embedded.status_code == 200
        assert 'src="/studio-assets/report-embed.js"' in embedded.text
        variants = requests.get(base + '/api/progress?folder=lecture', timeout=5).json()['report_variants']
        assert {item['name'] for item in variants} == {'', 'auto'}
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
