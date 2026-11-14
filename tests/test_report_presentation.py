"""Presentation compatibility never rewrites saved evidence or editor state."""
import hashlib
import threading
from functools import partial
from http.server import ThreadingHTTPServer

import requests

from video_descriptor.report import with_editor_control_roles
from video_descriptor.serve import RangeRequestHandler


def test_legacy_controls_receive_only_reviewed_roles_and_keep_content():
    original = '''<h1 id="lecture-title">Мой материал</h1>
<div class="notes-toolbar"><button data-notes-view="read">Читать</button></div>
<button id="save-notes" disabled>Сохранить</button>
<button id="download-html" class="export" title='literal class="do-not-change"'>HTML</button>
<button id="unrelated">Other</button>
<textarea id="editor-seed">&lt;button id="save-notes"&gt;Моя правка&lt;/button&gt;</textarea>
<textarea><button id="save-notes">Literal manual HTML</button></textarea>
<script>const text = '<button id="save-notes">not markup</button>';</script>'''
    styled = with_editor_control_roles(original)
    assert 'class="notes-toolbar vd-mode-switch"' in styled
    assert 'id="save-notes" disabled class="vd-button vd-button--primary vd-button--compact"' in styled
    assert 'class="export vd-button vd-button--quiet vd-button--compact"' in styled
    assert 'title=\'literal class="do-not-change"\'' in styled
    assert '<button id="unrelated">Other</button>' in styled
    assert '<textarea><button id="save-notes">Literal manual HTML</button></textarea>' in styled
    for tag in ('textarea', 'script'):
        fragment = original.split(f'<{tag}', 1)[1].split(f'</{tag}>', 1)[0]
        assert f'<{tag}{fragment}</{tag}>' in styled
    assert with_editor_control_roles(styled) == styled


def test_roles_handle_multiline_and_self_closing_tags_without_changing_other_bytes():
    original = '<p>Первая строка</p>\n<input\n id="title-input" class=old />\n<button CLASS=old id="cancel-title">Отмена</button>\n'
    styled = with_editor_control_roles(original)
    assert '<input\n id="title-input" class="old vd-input" />' in styled
    assert '<button class="old vd-button" id="cancel-title">Отмена</button>' in styled
    assert styled.startswith('<p>Первая строка</p>\n')
    assert styled.endswith('Отмена</button>\n')
    assert with_editor_control_roles(styled) == styled
    assert with_editor_control_roles('') == ''


def test_embedded_response_styles_legacy_html_without_rewriting_files(tmp_path):
    folder = tmp_path / 'output' / 'lecture'
    folder.mkdir(parents=True)
    (folder / 'manifest.json').write_text('{}', encoding='utf-8')
    (folder / 'notes.json').write_text('{}', encoding='utf-8')
    original = '''<html><h1 id="lecture-title">Исходный отчёт</h1>
<div class="notes-toolbar"><button data-notes-view="read">Конспект</button></div>
<button id="save-notes" disabled>Сохранить</button>
<link rel="stylesheet" href="assets/editor.css"><script src="assets/editor.js"></script>
<script src="assets/subtitle-report.js"></script></html>'''
    (folder / 'report.html').write_text(original, encoding='utf-8')
    (folder / 'notes.user.md').write_text('Мой текст', encoding='utf-8')
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(RangeRequestHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = requests.get(f'http://127.0.0.1:{server.server_port}/output/lecture/report.html?embedded=1', timeout=5)
        assert response.status_code == 200
        assert 'notes-toolbar vd-mode-switch' in response.text
        assert 'vd-button vd-button--primary vd-button--compact' in response.text
        assert 'href="/studio-assets/editor.css"' in response.text
        assert 'src="/studio-assets/editor.js"' in response.text
        assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()} == before
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
