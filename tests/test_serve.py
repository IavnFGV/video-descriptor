import threading
from functools import partial
from http.server import ThreadingHTTPServer

import pytest
import requests

from video_descriptor.serve import RangeRequestHandler


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


def test_unsatisfiable_range_and_full_file(server):
    response = requests.get(server, headers={"Range": "bytes=20-"}, timeout=5)
    assert response.status_code == 416
    assert response.headers["Content-Range"] == "bytes */10"
    response = requests.get(server, timeout=5)
    assert response.status_code == 200
    assert response.content == b"0123456789"
    assert response.headers["Accept-Ranges"] == "bytes"


def test_head_range_has_no_body(server):
    response = requests.head(server, headers={"Range": "bytes=2-5"}, timeout=5)
    assert response.status_code == 206
    assert response.content == b""
    assert response.headers["Content-Length"] == "4"
