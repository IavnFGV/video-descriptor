"""Collect public upstream metadata and small source files; never downloads models."""
import concurrent.futures
import json
import urllib.error
import urllib.request
from pathlib import Path

REPOS = ['rongtianjie/SubWeaver', 'fdff87554/whisper-ui',
         'artificemachine/vidistiller', 'jaypetersdotdev/self-hosted-video-starter-kit',
         'chidiwilliams/buzz', 'SubtitleEdit/subtitleedit', 'thewh1teagle/vibe',
         'jhj0517/Whisper-WebUI']
ROOT = Path(__file__).resolve().parents[1] / 'docs' / 'research'


def get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'video-descriptor-research'})
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read().decode('utf-8', errors='replace')


def collect(repo):
    folder = ROOT / 'raw' / repo.replace('/', '--')
    folder.mkdir(parents=True, exist_ok=True)
    meta = json.loads(get('https://api.github.com/repos/' + repo))
    branch = meta['default_branch']
    row = {key: meta.get(key) for key in ('full_name', 'html_url', 'default_branch',
           'pushed_at', 'archived', 'license', 'description')}
    commits = json.loads(get(f'https://api.github.com/repos/{repo}/commits?per_page=1'))
    row['head'] = commits[0]['sha']
    row['last_commit_date'] = commits[0]['commit']['committer']['date']
    row['files'] = []
    for name in ['README.md', 'LICENSE', 'LICENSE.md', 'LICENSE.txt',
                 'docker-compose.yml', 'compose.yaml', 'pyproject.toml']:
        url = f'https://raw.githubusercontent.com/{repo}/{row["head"]}/{name}'
        try:
            content = get(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        (folder / name).write_text(content, encoding='utf-8')
        row['files'].append({'path': name, 'url': url})
    return row


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        pending = {pool.submit(collect, repo): repo for repo in REPOS}
        for future in concurrent.futures.as_completed(pending):
            repo = pending[future]
            try:
                row = future.result()
                print(repo, row['last_commit_date'],
                      (row['license'] or {}).get('spdx_id'), flush=True)
                rows.append(row)
            except Exception as exc:
                rows.append({'repo': repo, 'error': str(exc)})
                print(repo, str(exc), flush=True)
    (ROOT / 'upstream-snapshot.json').write_text(json.dumps({
        'checked_on': '2026-10-16', 'repositories': sorted(rows, key=lambda r: r.get('full_name', r.get('repo')))
    }, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
