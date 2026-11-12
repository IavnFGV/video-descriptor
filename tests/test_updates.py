import importlib.util
import json
import subprocess
import threading
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('updates', ROOT / 'windows-app/updates.py')
updates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updates)


def release(tag='v0.9.3-build.8', **fields):
    return {'tag_name': tag, 'draft': False, 'prerelease': False, 'name': 'Release title',
            'body': '<script>untrusted</script>', 'published_at': '2026-11-12T10:00:00Z',
            'html_url': 'https://evil.invalid',
            'assets': [{'name': f'VideoDescriptor-{tag[1:]}-windows-x64-setup.exe', 'size': 123}], **fields}


@pytest.mark.parametrize('installed,available,expected', [
    ('v0.9.3-build.7', 'v0.9.3-build.8', True),
    ('v0.9.3-build.8', 'v0.9.4-build.1', True),
    ('v0.9.4-build.1', 'v0.9.3-build.100', False),
    ('v0.9.4-build.8', 'v0.9.4-build.8', False),
    ('v0.9.4-build.9', 'v0.9.4-build.8', False)])
def test_comparison(installed, available, expected):
    assert (updates.version_tuple(available) > updates.version_tuple(installed)) == expected


@pytest.mark.parametrize('tag', ['v0.9.3', 'vbad', '', None, 'v0.9.3-build.0',
                                 'v0.9.3-build.08', 'v0.9.3-build.8-rc1', 'v0.9.3-build.8/path'])
def test_unsupported_tags(tag):
    assert updates.version_tuple(tag) is None


def mock_api(monkeypatch, pages):
    opener = Mock()
    responses = []
    for page in pages:
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = page if isinstance(page, bytes) else json.dumps(page).encode()
        responses.append(response)
    opener.open.side_effect = responses
    monkeypatch.setattr(updates.urllib.request, 'build_opener', lambda *args: opener)
    return opener


def test_unsorted_paginated_selection_and_metadata(monkeypatch):
    page = [release('v0.9.4-build.2'), release('v0.9.3-build.100'), release('v0.9.4-build.1')]
    page += [release(draft=True), release(prerelease=True), release(assets=[]), {}, None,
             release('v5.0.0'), release('v8.0.0-build.1', assets=[{'name': 'Domestic-setup.exe', 'size': 5}])]
    page += [{}] * (100-len(page))
    opener = mock_api(monkeypatch, [page, [release('v0.9.4-build.3')]])
    result = updates.github_releases()
    assert result['tag'] == 'v0.9.4-build.3'
    assert result['url'] == updates.RELEASES + result['tag']
    assert result['notes'] == '<script>untrusted</script>'
    assert result['title'] == 'Release title'
    assert result['published_at'] == '2026-11-12T10:00:00Z'
    assert opener.open.call_count == 2
    request = opener.open.call_args.args[0]
    assert request.full_url == updates.API+'?per_page=100&page=2'
    assert request.get_header('Accept') == 'application/vnd.github+json'
    assert request.get_header('User-agent')
    assert opener.open.call_args.kwargs['timeout'] == 10


@pytest.mark.parametrize('data', [b'broken', b'{}', b'null', b'x' * (updates.MAX_BYTES+1)],
                         ids=['invalid-json', 'object', 'null', 'oversized'])
def test_invalid_network_responses(monkeypatch, data):
    mock_api(monkeypatch, [data])
    with pytest.raises((ValueError, TypeError)):
        updates.github_releases()


def test_empty_and_pagination_bound(monkeypatch):
    mock_api(monkeypatch, [[]])
    assert updates.github_releases() is None
    monkeypatch.setattr(updates, 'MAX_PAGES', 1)
    mock_api(monkeypatch, [[{}]*100])
    with pytest.raises(ValueError, match='pagination'):
        updates.github_releases()


@pytest.mark.parametrize('fields', [{'published_at': None}, {'published_at': 'bad'}, {'assets': {}},
                                  {'draft': 'false'}, {'assets': [{'name': 'setup.exe', 'size': 1}]}])
def test_malformed_metadata(fields):
    assert updates.release_info(release(**fields)) is None


def checker(tmp_path, **kwargs):
    return updates.UpdateChecker('0.9.3', 7, tmp_path/'updates.json', **kwargs)


def test_cache_interval_expiry_and_forced_refresh(tmp_path):
    now = [100000.0]
    fetch = Mock(return_value=updates.release_info(release()))
    service = checker(tmp_path, fetch=fetch, clock=lambda: now[0])
    service.check()
    assert service.snapshot()['update_available']
    cached = checker(tmp_path, fetch=fetch, clock=lambda: now[0])
    assert cached.snapshot() == service.snapshot()
    cached.check()
    assert fetch.call_count == 1
    cached.check(force=True)
    assert fetch.call_count == 2
    cached.request()
    cached.check()
    assert fetch.call_count == 3
    now[0] += updates.INTERVAL
    cached.check()
    assert fetch.call_count == 4


@pytest.mark.parametrize('error', [TimeoutError(), ConnectionError(), ValueError('invalid JSON'),
                                  urllib.error.URLError('connection failed'), updates.RateLimited(3600)])
def test_failure_retains_cache_and_backs_off(tmp_path, error):
    now = [100000.0]
    fetch = Mock(return_value=updates.release_info(release()))
    service = checker(tmp_path, fetch=fetch, clock=lambda: now[0])
    service.check()
    old = service.snapshot()
    fetch.side_effect = error
    service.check(force=True)
    result = service.snapshot()
    assert result['latest'] == old['latest']
    assert result['last_successful_check'] == old['last_successful_check']
    assert result['status'] == 'unavailable'
    service.request()
    service.check(force=True)
    assert fetch.call_count == 2
    now[0] = service.retry_at
    fetch.side_effect = None
    service.check(force=True)
    assert service.snapshot()['status'] == 'ok'


@pytest.mark.parametrize('code', [403, 429])
def test_rate_limit_headers(monkeypatch, code):
    opener = mock_api(monkeypatch, [])
    opener.open.side_effect = urllib.error.HTTPError(updates.API, code, 'limited', {'Retry-After': '7200'}, None)
    with pytest.raises(updates.RateLimited) as caught:
        updates.github_releases()
    assert caught.value.delay == 7200


def test_concurrent_manual_checks_and_shutdown(tmp_path):
    entered, finish = threading.Event(), threading.Event()
    def fetch():
        entered.set()
        assert finish.wait(5)
        return updates.release_info(release())
    fetch = Mock(side_effect=fetch)
    service = checker(tmp_path, fetch=fetch)
    service.start()
    try:
        service.request()
        assert entered.wait(5)
        for _ in range(30):
            service.request()
            service.check(force=True)
        assert service.snapshot()['status'] == 'checking'
    finally:
        finish.set()
        service.close()
        service.thread.join(5)
    assert not service.thread.is_alive()
    assert fetch.call_count == 1


@pytest.mark.parametrize('failure,expected', [(False, updates.INTERVAL), (True, 900)])
def test_owned_scheduler_startup_and_next_wakeup(tmp_path, failure, expected):
    now = [100000.0]
    fetch = Mock(side_effect=TimeoutError()) if failure else Mock(return_value=None)
    service = checker(tmp_path, fetch=fetch, clock=lambda: now[0])
    delays = []
    def wait(delay):
        delays.append(delay)
        now[0] += delay
        if len(delays) == 2:
            service.stop.set()
    service.wake = SimpleNamespace(wait=wait, clear=lambda: None)
    service._run()
    assert delays == [10, expected]
    assert fetch.call_count == 1


@pytest.mark.parametrize('build,supported', [(None, True), (0, True), (7, False)])
def test_development_never_notifies(tmp_path, build, supported):
    fetch = Mock()
    service = updates.UpdateChecker('0.9.3', build, tmp_path/'cache', supported=supported, fetch=fetch)
    service.check(force=True)
    service.request()
    service.start()
    assert service.snapshot()['status'] == 'unsupported'
    assert not service.snapshot()['update_available']
    fetch.assert_not_called()


def test_corrupt_and_untrusted_cache(tmp_path):
    path = tmp_path/'updates.json'
    path.write_text('[]')
    assert checker(tmp_path).snapshot()['last_successful_check'] is None
    service = checker(tmp_path, fetch=lambda: updates.release_info(release()))
    service.check()
    value = json.loads(path.read_text())
    value['latest']['url'] = 'https://evil.invalid'
    path.write_text(json.dumps(value))
    assert checker(tmp_path).snapshot()['latest']['url'] == updates.RELEASES+'v0.9.3-build.8'


def test_empty_result_is_cached_and_unwritable_cache_is_nonfatal(tmp_path):
    fetch = Mock(return_value=None)
    service = checker(tmp_path, fetch=fetch)
    service.check()
    assert service.snapshot()['status'] == 'ok'
    assert not service.snapshot()['update_available']
    checker(tmp_path, fetch=fetch).check()
    assert fetch.call_count == 1
    # A file as parent directory deterministically refuses cache writes, even as admin.
    parent = tmp_path/'not-directory'
    parent.write_text('fixture')
    service = updates.UpdateChecker('0.9.3', 7, parent/'cache', fetch=lambda: updates.release_info(release()))
    service.check()
    assert service.snapshot()['status'] == 'ok'
    assert service.snapshot()['update_available']


def test_redirect_rejected():
    with pytest.raises(ValueError, match='redirect'):
        updates.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://evil.invalid')


def test_packaged_module_and_ui():
    spec = importlib.util.spec_from_file_location('build_release_updates', ROOT/'windows-app/build_release.py')
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    paths = build.source_paths()
    for name in ('updates.py', 'ui/updates.js'):
        assert ROOT/'windows-app'/name in paths
    subprocess.run(['node', str(ROOT/'tests/updates_ui.cjs')], check=True, cwd=ROOT)


def test_local_api_guards_audit_and_external_navigation(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('updates_native_app', ROOT/'windows-app/app.py')
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    import component_manager
    import compute
    import setup_service
    import storage_service
    monkeypatch.setattr(compute, 'ComputeManager', lambda *args: SimpleNamespace(_lock=threading.RLock()))
    monkeypatch.setattr(setup_service, 'SetupService', lambda *args: SimpleNamespace(bootstrap=lambda: None))
    monkeypatch.setattr(component_manager, 'ComponentManager', lambda *args, **kwargs: None)
    monkeypatch.setattr(storage_service, 'StorageService', lambda *args: None)
    opened = Mock()
    monkeypatch.setattr(app.webbrowser, 'open', opened)
    events = tmp_path/'logs/events.jsonl'
    monkeypatch.setenv('VIDEO_DESCRIPTOR_EVENTS', str(events))
    service = checker(tmp_path, fetch=lambda: updates.release_info(release()))
    service.check()
    with ThreadingHTTPServer(('127.0.0.1', 0), app.make_handler(
            {'workspace': str(tmp_path), 'npu_worker_directory': 'unused'}, 'instance', service)) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            assert requests.get(base+'/api/updates', timeout=3).json()['update_available']
            assert requests.post(base+'/api/updates/check', timeout=3).status_code == 403
            headers = {'X-App-Instance': 'instance'}
            assert requests.post(base+'/api/updates/check', headers={**headers, 'Origin': 'https://evil.invalid'}, timeout=3).status_code == 403
            assert requests.post(base+'/api/updates/check', headers=headers, timeout=3).json()['status'] == 'checking'
            response = requests.post(base+'/api/setup/external', headers=headers,
                                     json={'page': 'update-release', 'url': 'https://evil.invalid'}, timeout=3)
            assert response.status_code == 200
            opened.assert_called_once_with(updates.RELEASES+'v0.9.3-build.8')
            assert requests.get(base+'/updates.js', timeout=3).status_code == 200
        finally:
            server.shutdown()
            thread.join()
    logged = [json.loads(line) for line in events.read_text(encoding='utf-8').splitlines()]
    assert any(e['action'] == 'update_check' and e['status'] == 'done' for e in logged)
    assert any(e.get('route') == '/api/updates/check' for e in logged)
