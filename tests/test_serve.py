import threading
from functools import partial
from http.server import ThreadingHTTPServer
from unittest.mock import Mock

import pytest
import requests

from video_descriptor.serve import RangeRequestHandler


def test_delete_version_requires_same_origin_and_updates_inventory(server, tmp_path):
    from video_descriptor.jobs import write_json

    folder = tmp_path / 'output' / 'test-version'
    folder.mkdir(parents=True)
    write_json(folder / 'manifest.json', {'video': str(tmp_path / 'video.mp4')})
    base = server.removesuffix('/video.mp4')
    response = requests.post(base + '/api/delete-version', json={'folder': 'test-version'},
                             headers={'Origin': 'https://other.example'}, timeout=5)
    assert response.status_code == 403
    assert folder.exists()
    response = requests.post(base + '/api/delete-version', json={'folder': 'test-version'}, timeout=5)
    assert response.status_code == 200
    assert response.json() == {'deleted': 'test-version'}
    assert not folder.exists()
    assert (tmp_path / 'video.mp4').read_bytes() == b'0123456789'
    assert requests.get(base + '/api/runs', timeout=5).json() == []


@pytest.fixture
def server(tmp_path):
    (tmp_path / "video.mp4").write_bytes(b"0123456789")
    handler = partial(RangeRequestHandler, directory=str(tmp_path))
    http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{http.server_port}/video.mp4"
    http.shutdown()
    http.server_close()
    thread.join()


@pytest.mark.parametrize("header,body,content_range", [
    ("bytes=2-5", b"2345", "bytes 2-5/10"),
    ("bytes=7-", b"789", "bytes 7-9/10"),
    ("bytes=-3", b"789", "bytes 7-9/10"),
    ("bytes=8-100", b"89", "bytes 8-9/10"),
])
def test_video_ranges(server, header, body, content_range):
    response = requests.get(server, headers={"Range": header}, timeout=5)
    assert response.status_code == 206
    assert response.content == body
    assert response.headers["Content-Range"] == content_range
    assert int(response.headers["Content-Length"]) == len(body)
    assert response.headers["Accept-Ranges"] == "bytes"


@pytest.mark.parametrize("path,location", [
    ("/speech?folder=speech-example", "/create?folder=speech-example"),
    ("/speech?job=abc", "/create?job=abc"),
    ("/studio-assets/speech.html", "/create"),
])
def test_speech_links_open_unified_workspace(server, path, location):
    base = server.removesuffix("/video.mp4")
    response = requests.get(base + path, allow_redirects=False, timeout=5)
    assert response.status_code == 302
    assert response.headers["Location"] == location
    workspace = requests.get(base + path, timeout=5)
    assert workspace.status_code == 200
    assert 'id="speech-feed"' in workspace.text
    assert 'id="speaker-names-form"' in workspace.text
    assert 'src="/studio-assets/create.js"' in workspace.text


def test_editable_prompt_api_persists_and_checks_origin(server, tmp_path):
    base = server.removesuffix('/video.mp4')
    response = requests.get(base + '/api/prompts', timeout=5)
    assert response.status_code == 200
    assert 'summarize' in response.json()['prompts']
    response = requests.post(base + '/api/prompts', json={'task': 'summarize', 'text': 'Мой промпт'}, timeout=5)
    assert response.status_code == 200
    assert requests.get(base + '/api/prompts', timeout=5).json()['prompts']['summarize'] == 'Мой промпт'
    assert requests.post(base + '/api/prompts', json={'task': 'summarize', 'text': 'Другой'},
                         headers={'Origin': 'https://other.example'}, timeout=5).status_code == 403
    assert requests.get(base + '/.devcontainer/model-prompts.json', timeout=5).status_code == 403


def test_english_subtitle_editor_and_both_downloads(server, tmp_path):
    import json
    folder = tmp_path / 'output' / 'english'
    folder.mkdir(parents=True)
    (folder / 'transcript.json').write_text(json.dumps([
        {'id': 's1', 'start': 1, 'end': 3, 'text': 'Hello'}]))
    (folder / 'translations.json').write_text(json.dumps({'s1': 'Привет'}))
    base = server.removesuffix('/video.mp4')
    result = requests.get(base + '/api/speech?folder=english', timeout=5).json()['result']
    response = requests.post(base + '/api/speech-edit', json={
        'folder': 'english', 'revision': result['edit_revision'], 'index': 0,
        'action': 'edit', 'text': 'Goodbye', 'speaker': 'unknown', 'translation': 'Пока'}, timeout=5)
    assert response.status_code == 200
    for language, expected in [('original', 'Goodbye'), ('ru', 'Пока')]:
        response = requests.get(base + f'/api/subtitles?folder=english&language={language}', timeout=5)
        assert response.status_code == 200
        assert 'attachment' in response.headers['Content-Disposition']
        assert response.headers['Content-Type'] == 'text/vtt; charset=utf-8'
        assert '00:00:01.000 --> 00:00:03.000' in response.text
        assert expected in response.text
    assert requests.get(base + '/api/subtitles?folder=..', timeout=5).status_code == 404


def test_unsatisfiable_range_and_full_file(server):
    response = requests.get(server, headers={"Range": "bytes=20-"}, timeout=5)
    assert response.status_code == 416
    assert response.headers["Content-Range"] == "bytes */10"
    response = requests.get(server, timeout=5)
    assert response.status_code == 200
    assert response.content == b"0123456789"
    assert response.headers["Accept-Ranges"] == "bytes"


def test_settings_api_does_not_return_or_serve_secret(server, tmp_path):
    base = server.removesuffix("/video.mp4")
    response = requests.post(base + "/api/translation-settings",
                             json={"provider": "gemini", "api_key": "private-test-secret"},
                             timeout=5)
    assert response.status_code == 200
    assert response.json()["has_key"]
    assert "private-test-secret" not in response.text
    response = requests.get(base + "/api/translation-settings", timeout=5)
    assert "private-test-secret" not in response.text
    assert "api_key" not in response.json()
    for path in ("/.devcontainer/translation-settings.json", "/%2edevcontainer/translation-settings.json"):
        response = requests.get(base + path, timeout=5)
        assert response.status_code == 403
        assert "private-test-secret" not in response.text
    response = requests.post(base + "/api/translation-settings",
                             json={"api_key": "another-key"},
                             headers={"Origin": "https://another-site.example"}, timeout=5)
    assert response.status_code == 403


def test_head_range_has_no_body(server):
    response = requests.head(server, headers={"Range": "bytes=2-5"}, timeout=5)
    assert response.status_code == 206
    assert response.content == b""
    assert response.headers["Content-Length"] == "4"


def test_source_title_can_be_saved_before_notes_exist(server, tmp_path):
    import json
    folder = tmp_path / 'output' / 'source-only'
    folder.mkdir(parents=True)
    (folder / 'manifest.json').write_text(json.dumps({'video': 'recording.mp4'}))
    base = server.removesuffix('/video.mp4')
    response = requests.post(base + '/output/source-only/title.json', json={'title': 'New name'}, timeout=5)
    assert response.status_code == 200
    assert response.json()['title'] == 'New name'
    assert not (folder / 'report.html').exists()


def test_invalid_speech_only_flag_does_not_create_a_job(server, tmp_path, monkeypatch):
    start = Mock()
    monkeypatch.setattr('video_descriptor.serve.start_worker', start)
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'recording.mp4').write_bytes(b'video')
    base = server.removesuffix('/video.mp4')
    response = requests.post(base + '/api/speech-run', json={
        'video': 'data/recording.mp4', 'engine': 'whisper', 'speech_only': 'true'}, timeout=5)
    assert response.status_code == 400
    assert not list(tmp_path.glob('output/jobs/*/job.json'))
    start.assert_not_called()
