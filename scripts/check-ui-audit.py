"""Stage-0 guard: production source identity and desktop DOM hook inventory.

Run with Python standard library. --record creates baseline once from git HEAD;
never silently refresh the snapshot during a later UI migration.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'design-system/baseline.json'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def digest(data):
    # Git blobs are LF; worktrees may use CRLF. Compare semantic byte identity
    # after only newline normalization, never whitespace/content stripping.
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def inventory(files):
    result = {}
    for name, data in files.items():
        if not name.endswith(('.html', '.js')):
            continue
        source = data.decode('utf-8')
        result[name] = {
            'ids': sorted(set(re.findall(r'\bid="([^"]+)"', source))) if name.endswith('.html') else [],
            'direct_id_refs': sorted(set(re.findall(r"\$\(['\"]([^'\"]+)['\"]\)", source))),
            'api_literals': sorted(set(re.findall(r"['\"](/api/[^'\"\s]*)['\"]", source))),
        }
    return result


def main():
    if '--record' in sys.argv:
        if BASELINE.exists():
            raise SystemExit('Baseline already exists; contract-review required before replacing it.')
        names = git('ls-files', 'windows-app', 'video_descriptor').decode().splitlines()
        names = [p for p in names if p.endswith(('.py', '.js', '.css', '.html', '.cs', '.json'))]
        files = {p: git('show', 'HEAD:' + p) for p in names}
        value = {'commit': git('rev-parse', 'HEAD').decode().strip(),
                 'normalization': 'CRLF to LF only',
                 'sha256': {p: digest(data) for p, data in files.items()},
                 'inventory': inventory(files)}
        BASELINE.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
    failures = []
    for name, expected in baseline['sha256'].items():
        path = ROOT / name
        if not path.is_file() or digest(path.read_bytes()) != expected:
            failures.append('Production file changed: ' + name)
    html = (ROOT / 'windows-app/ui/index.html').read_text(encoding='utf-8')
    js = (ROOT / 'windows-app/ui/app.js').read_text(encoding='utf-8')
    ids = re.findall(r'\bid="([^"]+)"', html)
    refs = set(re.findall(r"\$\(['\"]([^'\"]+)['\"]\)", js))
    failures.extend('Missing desktop handler target: ' + name for name in sorted(refs - set(ids)))
    if len(ids) != len(set(ids)):
        failures.append('Duplicate desktop ids')
    if failures:
        print('\n'.join(failures))
        return 1
    print(f"PASS: {len(baseline['sha256'])} production files unchanged; "
          f'{len(ids)} unique desktop ids; {len(refs)} direct handler targets resolved.')
    print('Static preservation check only; not a backend or WebView2 E2E test.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
