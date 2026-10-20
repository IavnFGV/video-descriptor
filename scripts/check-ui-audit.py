"""Production preservation guard with explicitly reviewed UI migrations.

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
    migrations = {} if '--stage-zero' in sys.argv else json.loads(
        (ROOT / 'design-system/migrations/main.json').read_text(encoding='utf-8'))['allowed_changes']
    unchanged = 0
    for name, expected in baseline['sha256'].items():
        path = ROOT / name
        if not path.is_file() or digest(path.read_bytes()) != expected:
            if name not in migrations:
                failures.append('Unreviewed production file changed: ' + name)
        else:
            unchanged += 1
    html = (ROOT / 'windows-app/ui/index.html').read_text(encoding='utf-8')
    js = (ROOT / 'windows-app/ui/app.js').read_text(encoding='utf-8')
    ids = re.findall(r'\bid="([^"]+)"', html)
    refs = set(re.findall(r"\$\(['\"]([^'\"]+)['\"]\)", js))
    failures.extend('Missing desktop handler target: ' + name for name in sorted(refs - set(ids)))
    original = baseline['inventory']
    previous_ids = set(original['windows-app/ui/index.html']['ids'])
    failures.extend('Original desktop id removed: ' + name for name in sorted(previous_ids - set(ids)))
    previous_apis = set(original['windows-app/ui/app.js']['api_literals'])
    current_apis = set(re.findall(r"['\"](/api/[^'\"\s]*)['\"]", js))
    # Explicit additive Stop contract, reviewed in migrations/main.json and CONTRACTS.md.
    if previous_apis | {'/api/native/cancel?id=', '/api/components', '/api/setup/ollama?discover=1'} != current_apis:
        failures.append('Desktop API literals changed; explicit API contract review required')
    original_js = git('show', baseline['commit'] + ':windows-app/ui/app.js').decode('utf-8')
    pattern = r"\$\(['\"]([^'\"]+)['\"]\)\.(on\w+)\s*="
    before, after = set(re.findall(pattern, original_js)), set(re.findall(pattern, js))
    failures.extend('Original handler removed: ' + '.'.join(pair) for pair in sorted(before - after))
    if len(ids) != len(set(ids)):
        failures.append('Duplicate desktop ids')
    # Review each migrated module against the immutable manifest, including workspace.
    for name in migrations:
        if not name.endswith(('.html', '.js')) or name.startswith('windows-app/'):
            continue
        current = (ROOT / name).read_text(encoding='utf-8')
        previous = original.get(name, {})
        if name.endswith('.html'):
            current_ids = re.findall(r'\bid="([^"]+)"', current)
            failures.extend(name + ': original id removed: ' + item
                            for item in set(previous.get('ids', [])) - set(current_ids))
            if len(current_ids) != len(set(current_ids)):
                failures.append(name + ': duplicate ids')
        else:
            apis = set(re.findall(r"['\"](/api/[^'\"\s]*)['\"]", current))
            failures.extend(name + ': original API literal removed: ' + item
                            for item in set(previous.get('api_literals', [])) - apis)
            old_source = git('show', baseline['commit'] + ':' + name).decode('utf-8')
            failures.extend(name + ': original handler removed: ' + '.'.join(pair)
                            for pair in set(re.findall(pattern, old_source)) - set(re.findall(pattern, current)))
    if failures:
        print('\n'.join(failures))
        return 1
    if migrations:
        subprocess.run([sys.executable, str(ROOT / 'scripts/build-ui-css.py'), '--check'], check=True)
    print(f"PASS: {unchanged} production files unchanged; {len(migrations)} reviewed UI paths; "
          f'{len(ids)} unique desktop ids; {len(refs)} direct handler targets resolved.')
    print(f'{len(previous_ids)} original ids, {len(before)} handler assignments and API literals preserved.')
    print('Static contract checks only; browser scenarios and backend tests are separate.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
