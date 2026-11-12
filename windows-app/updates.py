"""Notification-only official Windows release checks. No asset downloads."""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from http.client import HTTPException
from pathlib import Path

from video_descriptor.action_history import record

API = 'https://api.github.com/repos/IavnFGV/video-descriptor/releases'
RELEASES = 'https://github.com/IavnFGV/video-descriptor/releases/tag/'
INTERVAL = 24 * 3600
MAX_BYTES = 2 * 1024 * 1024
MAX_PAGES = 100
TAG = re.compile(r'v(\d+)\.(\d+)\.(\d+)-build\.([1-9]\d*)', re.ASCII)


def version_tuple(tag):
    # Legacy vX.Y.Z is valid for release retries, but has no comparable BUILD.
    match = TAG.fullmatch(tag) if isinstance(tag, str) and len(tag) <= 100 else None
    return tuple(map(int, match.groups())) if match else None


def release_info(release):
    if not isinstance(release, dict) or release.get('draft') is not False or release.get('prerelease') is not False:
        return None
    tag = release.get('tag_name')
    version = version_tuple(tag)
    if version is None:
        return None
    product, build = tag[1:].split('-build.')
    installer = f'VideoDescriptor-{product}-build.{build}-windows-x64-setup.exe'
    assets = release.get('assets')
    if not isinstance(assets, list) or not any(isinstance(a, dict) and a.get('name') == installer
                                              and type(a.get('size')) is int and a['size'] > 0 for a in assets):
        return None
    published = release.get('published_at')
    try:
        if not isinstance(published, str) or datetime.fromisoformat(published).tzinfo is None:
            return None
    except ValueError:
        return None
    # Never trust API-provided navigation URLs, including those in cached metadata.
    return {'version': product, 'build': version[3], 'tag': tag,
            'title': str(release.get('name') or tag)[:200],
            'notes': str(release.get('body') or '')[:4000],
            'published_at': published[:64], 'url': RELEASES + tag}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Unexpected GitHub redirect')


class RateLimited(Exception):
    def __init__(self, delay):
        self.delay = delay


def github_releases():
    """Scan every page; an incomplete scan must never replace a successful result."""
    opener = urllib.request.build_opener(NoRedirect())
    best = None
    deadline = time.monotonic() + 120
    for page in range(1, MAX_PAGES + 1):
        if time.monotonic() >= deadline:
            raise TimeoutError('Release scan timed out')
        request = urllib.request.Request(f'{API}?per_page=100&page={page}', headers={
            'User-Agent': 'VideoDescriptor-update-check', 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with opener.open(request, timeout=10) as response:
                data = response.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if exc.code in {403, 429}:
                try:
                    delay = max(float(exc.headers.get('Retry-After', 0)),
                                float(exc.headers.get('X-RateLimit-Reset', 0)) - time.time())
                except (ValueError, TypeError):
                    delay = 3600
                raise RateLimited(min(INTERVAL, max(3600, delay))) from None
            raise
        if len(data) > MAX_BYTES:
            raise ValueError('GitHub response too large')
        rows = json.loads(data)
        if not isinstance(rows, list):
            raise TypeError('Invalid GitHub release list')
        for row in rows:
            info = release_info(row)
            if info and (best is None or version_tuple(info['tag']) > version_tuple(best['tag'])):
                best = info
        if len(rows) < 100:
            return best
    raise ValueError('GitHub pagination limit exceeded')


class UpdateChecker:
    def __init__(self, version, build, cache, *, supported=True, fetch=github_releases, clock=time.time):
        self.installed = {'version': version, 'build': build}
        self.supported = supported and type(build) is int and build > 0 and version_tuple(f'v{version}-build.{build}') is not None
        self.cache = Path(cache)
        self.fetch, self.clock = fetch, clock
        self.lock = threading.Lock()
        self.wake, self.stop = threading.Event(), threading.Event()
        self.thread = None
        self.latest, self.checked = None, None
        self.status = 'idle' if self.supported else 'unsupported'
        self.pending = False
        self.failures = 0
        self.retry_at = 0
        self._load()

    def _load(self):
        try:
            if self.cache.stat().st_size > 32 * 1024:
                return
            value = json.loads(self.cache.read_text(encoding='utf-8'))
            checked = value['last_successful_check']
            latest = value['latest']
            if type(checked) not in {int, float} or not 0 < checked <= self.clock():
                return
            if latest is not None:
                # Reuse the same validation and reconstruct the trusted URL.
                tag = latest['tag']
                latest = release_info({'draft': False, 'prerelease': False, 'tag_name': tag,
                                       'name': latest['title'], 'body': latest['notes'],
                                       'published_at': latest['published_at'],
                                       'assets': [{'name': 'VideoDescriptor-' + tag[1:] + '-windows-x64-setup.exe', 'size': 1}]})
                if latest is None:
                    return
            self.latest, self.checked = latest, checked
            if self.supported:
                self.status = 'ok'
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            pass

    def snapshot(self):
        with self.lock:
            return {'installed': dict(self.installed), 'latest': dict(self.latest) if self.latest else None,
                    'update_available': bool(self.supported and self.latest and
                                             version_tuple(self.latest['tag']) > version_tuple(
                                                 f'v{self.installed["version"]}-build.{self.installed["build"]}')),
                    'last_successful_check': self.checked, 'status': self.status}

    def request(self):
        with self.lock:
            # Manual requests bypass the success interval, not failure/rate-limit backoff.
            if not self.supported or self.pending or self.status == 'checking' or self.clock() < self.retry_at:
                return
            self.pending = True
            self.status = 'checking'
            self.wake.set()

    def check(self, force=False):
        """Single-flight check, called only by the owned worker (directly in tests)."""
        with self.lock:
            if not self.supported or self.clock() < self.retry_at:
                return
            if self.status == 'checking' and not self.pending:
                return
            if not force and not self.pending and self.checked and self.clock() < self.checked + INTERVAL:
                return
            self.pending = False
            self.status = 'checking'
        operation = uuid.uuid4().hex
        record('update_check', operation_id=operation, status='started')
        try:
            latest = self.fetch()
            checked = self.clock()
            try:
                self.cache.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.cache.with_suffix('.tmp')
                temporary.write_text(json.dumps({'latest': latest, 'last_successful_check': checked}), encoding='utf-8')
                temporary.replace(self.cache)
            except OSError:
                record('update_cache', operation_id=operation, status='error', reason='cache_write_failed')
            with self.lock:
                self.latest, self.checked, self.status = latest, checked, 'ok'
                self.failures, self.retry_at = 0, 0
            record('update_check', operation_id=operation, status='done')
        except (OSError, ValueError, TypeError, RecursionError, HTTPException, RateLimited) as exc:
            with self.lock:
                self.failures += 1
                delay = exc.delay if isinstance(exc, RateLimited) else min(INTERVAL, 900 * 2 ** min(self.failures - 1, 7))
                self.retry_at = self.clock() + delay
                self.status = 'unavailable'
            record('update_check', operation_id=operation, status='error', reason=type(exc).__name__)

    def start(self):
        if not self.supported or self.thread is not None:
            return
        self.thread = threading.Thread(target=self._run, name='release-updates', daemon=True)
        self.thread.start()

    def _run(self):
        delay = 10
        while not self.stop.is_set():
            self.wake.wait(delay)
            self.wake.clear()
            if self.stop.is_set():
                break
            self.check()
            with self.lock:
                due = max(self.retry_at, (self.checked + INTERVAL) if self.checked and not self.failures else 0)
                delay = max(1, due - self.clock())

    def close(self):
        self.stop.set()
        self.wake.set()
