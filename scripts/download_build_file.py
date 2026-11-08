"""Download pinned build tools with bounded retries and atomic cache publication."""
import argparse
import hashlib
import http.client
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit


def verified_download(url, destination, expected, attempts=4, fallback_url=None):
    if fallback_url:
        parsed = urlsplit(fallback_url)
        if (parsed.scheme != 'https' or parsed.netloc != 'api.github.com'
                or not re.fullmatch(r'/repos/[\w.-]+/[\w.-]+/releases/assets/\d+', parsed.path)
                or parsed.query or parsed.fragment):
            raise ValueError('Fallback must be an official GitHub release asset API URL')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        with destination.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() == expected:
                return destination
    for attempt in range(attempts):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=destination.name + '.', suffix='.part', delete=False) as output:
                temporary = Path(output.name)
                request = (urllib.request.Request(fallback_url + '?download=' + uuid.uuid4().hex,
                           headers={'Accept': 'application/octet-stream', 'User-Agent': 'video-descriptor-build'})
                           if attempt and fallback_url else url)
                with urllib.request.urlopen(request, timeout=30) as response:
                    shutil.copyfileobj(response, output)
            with temporary.open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != expected:
                    raise ValueError('Build download SHA256 mismatch: ' + destination.name)
            os.replace(temporary, destination)
            return destination
        except (OSError, ValueError, http.client.HTTPException) as error:
            retryable = not isinstance(error, urllib.error.HTTPError) or error.code in {408, 429, 500, 502, 503, 504}
            if not retryable or attempt + 1 == attempts:
                raise
            print(f'Build download {destination.name}: attempt {attempt + 1}/{attempts} failed ({error}); retrying', file=sys.stderr, flush=True)
            time.sleep(2 ** (attempt + 1))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--fallback-url')
    args = parser.parse_args()
    verified_download(args.url, args.output, args.sha256, fallback_url=args.fallback_url)
