"""Preview known generated files. --apply deletes only the revalidated allowlisted plan."""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from local_build import build_lock, git, remove_tree, state_dir

PACKAGE = re.compile(r'VideoDescriptor-(\d+\.\d+\.\d+)-windows-x64(?:-setup\.exe|\.zip)$')
VERSION = re.compile(r'\d+\.\d+\.\d+$')


def version(value):
    return tuple(map(int, value.split('.')))


def safe_size(path):
    """Refuse junctions/symlinks anywhere, including ancestors of the selected path."""
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or (hasattr(ancestor, 'is_junction') and ancestor.is_junction()):
            raise ValueError('Linked path is not eligible: ' + str(ancestor))
    if path.is_dir():
        total = 0
        for directory, subdirs, files in os.walk(path, followlinks=False):
            for name in [*subdirs, *files]:
                item = Path(directory) / name
                if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
                    raise ValueError('Linked content is not eligible: ' + str(item))
            total += sum((Path(directory) / name).stat().st_size for name in files)
        return total
    return path.stat().st_size


def plan(repo, config, keep=3, days=0):
    repo = repo.resolve()
    tracked = set(git(repo, 'ls-files').splitlines())
    cutoff = time.time() - days * 86400
    candidates, packages = [], []
    local_output = Path(config.get('output', repo / 'dist/local')).resolve()
    for base in dict.fromkeys((repo / 'dist', repo / 'dist-clean', local_output)):
        if not base.is_dir():
            continue
        for path in base.iterdir():
            if path.is_file() and (match := PACKAGE.fullmatch(path.name)):
                packages.append((match[1], path, base))
            elif VERSION.fullmatch(path.name) and path.is_dir():
                for package in path.iterdir():
                    if package.is_file() and (match := PACKAGE.fullmatch(package.name)):
                        packages.append((match[1], package, base))
    preserved = set(sorted({v for v, _, _ in packages}, key=version, reverse=True)[:keep])
    candidates += [(p, base, 'historical installer/archive') for v, p, base in packages if v not in preserved]
    if local_output.is_dir():
        runs = sorted((p for p in local_output.iterdir() if p.is_dir()
                       and re.fullmatch(r'[0-9a-f]{12}-\d{8}T\d{12}Z', p.name)
                       and (p / 'artifacts/provenance.json').is_file()),
                      key=lambda p: p.name.split('-', 1)[1], reverse=True)
        for run in runs[keep:]:
            candidates += [(p, local_output, 'historical automated build artifact')
                           for p in (run / 'artifacts').iterdir() if PACKAGE.fullmatch(p.name)]
    candidates += [(p, repo, 'old untracked root log') for p in repo.glob('*.log')
                   if p.name not in tracked and not p.name.startswith('.env') and p.stat().st_mtime < cutoff]
    cache = Path(config.get('cache', repo / 'windows-app/runtime/build-cache')).resolve()
    # Only disposable builder directories. Keep wheels, downloads, SDK, models and tools.
    for pattern in ('payload-*', 'vcrt-*'):
        if cache.is_dir():
            candidates += [(p, cache, 'old temporary build payload') for p in cache.glob(pattern)
                           if p.is_dir() and p.stat().st_mtime < cutoff]
    state = state_dir(repo)
    candidates += [(p, state, 'obsolete launcher log') for p in state.glob('launcher-*.log')]
    candidates += [(p, state, 'obsolete cleanup report') for pattern in ('cleanup-*.json', 'cleanup-*.txt')
                   for p in state.glob(pattern)]
    scratch = Path(config.get('temp_root', str(cache / 'temp'))).resolve()
    if scratch.is_dir():
        candidates += [(p, scratch, 'orphaned build scratch') for p in scratch.iterdir()
                       if p.is_dir() and re.fullmatch(r'[0-9a-f]{12}-\d{8}T\d{12}Z', p.name)]
    protected_logs = set()
    protected_bundles = set()
    for name in ('status.json', 'last-success.json'):
        path = state / name
        if path.exists():
            record = json.loads(path.read_text(encoding='utf-8'))
            if record.get('log'):
                protected_logs.add(Path(record['log']).resolve())
            if record.get('component_cache_key'):
                protected_bundles.add(record['component_cache_key'])
    canonical_outputs = set()
    for result in (state / 'results').glob('*.json'):
        record = json.loads(result.read_text(encoding='utf-8'))
        if record.get('state') == 'ready' and record.get('output'):
            canonical_outputs.add(Path(record['output']).resolve())
    for run in (state / 'runs').glob('*'):
        if not run.is_dir() or not re.fullmatch(r'[0-9a-f]{12}-\d{8}T\d{12}Z', run.name):
            continue
        for name in ('source', 'artifacts'):
            path = run / name
            if path.is_dir() and path.resolve() not in canonical_outputs:
                candidates.append((path, run, 'completed build scratch'))
        log = run / 'build.log'
        if log.is_file() and log.resolve() not in protected_logs:
            candidates.append((log, run, 'obsolete build log'))
    for name in ('.pytest_cache', '.ruff_cache'):
        path = repo / name
        if path.is_dir():
            candidates.append((path, repo, 'generated check cache'))
    for name in ('video_descriptor', 'tests', 'scripts', 'windows-app'):
        for directory, subdirs, _ in os.walk(repo / name, followlinks=False):
            subdirs[:] = [item for item in subdirs if item not in {'runtime', '.git', 'node_modules'}
                          and not item.startswith('.venv')]
            if '__pycache__' in subdirs:
                candidates.append((Path(directory) / '__pycache__', repo, 'generated bytecode cache'))
                subdirs.remove('__pycache__')
    bundles = cache / 'component-bundles'
    if bundles.is_dir():
        complete = sorted((p for p in bundles.iterdir() if p.is_dir() and
                           re.fullmatch(r'[0-9a-f]{64}', p.name) and (p / 'cache.json').is_file()),
                          key=lambda p: p.stat().st_mtime_ns, reverse=True)
        candidates += [(p, bundles, 'incomplete component cache') for p in bundles.iterdir()
                       if p.is_dir() and re.fullmatch(r'[0-9a-f]{64}', p.name) and not (p / 'cache.json').is_file()]
        retained = set(protected_bundles)
        for directory in complete:
            if len(retained) < 2:
                retained.add(directory.name)
        candidates += [(p, bundles, 'superseded component cache') for p in complete if p.name not in retained]
    short_temp = cache / 't'
    if short_temp.is_dir():
        candidates += [(p, short_temp, 'orphaned installer verification') for p in short_temp.glob('vc-*')
                       if p.is_dir()]
    entries, skipped = [], []
    for path, boundary, reason in candidates:
        try:
            # Validate absolute targets under explicitly named output/cache roots before deletion.
            absolute, allowed = path.resolve(), boundary.resolve()
            if absolute == allowed or not absolute.is_relative_to(allowed):
                raise ValueError('Target escapes cleanup boundary')
            if absolute.is_relative_to(repo):
                relative = absolute.relative_to(repo).as_posix()
                if relative in tracked or any(item.startswith(relative + '/') for item in tracked):
                    raise ValueError('Tracked source file')
            entries.append({'path': str(path.absolute()), 'boundary': str(allowed),
                            'bytes': safe_size(path), 'mtime_ns': path.stat().st_mtime_ns, 'reason': reason})
        except (OSError, ValueError) as error:
            skipped.append({'path': str(path), 'reason': str(error)})
    return {'preserved_versions': sorted(preserved, key=version), 'files': entries, 'skipped': skipped,
            'bytes': sum(entry['bytes'] for entry in entries)}


def apply_plan(report):
    # Preflight the full list before deleting anything; refuse changed or linked paths.
    for entry in report['files']:
        path, boundary = Path(entry['path']), Path(entry['boundary'])
        target = path.resolve()
        if target == boundary or not target.is_relative_to(boundary):
            raise ValueError('Cleanup target escaped its boundary')
        if path.stat().st_mtime_ns != entry['mtime_ns'] or safe_size(path) != entry['bytes']:
            raise ValueError('Cleanup target changed; generate a new preview: ' + str(path))
    for entry in report['files']:
        path = Path(entry['path'])
        # Recheck immediately before each recursive deletion.
        if not path.resolve().is_relative_to(Path(entry['boundary'])):
            raise ValueError('Cleanup target escaped its boundary')
        safe_size(path)
        if path.is_dir():
            remove_tree(path, Path(entry['boundary']))
        else:
            path.unlink()


def refuse_active_builds():
    import psutil
    for process in psutil.process_iter(['cmdline']):
        try:
            args = process.info['cmdline'] or []
            if any(Path(arg).name in {'build_release.py', 'verify_release.py', 'verify_domestic.py', 'verify_cached.py', 'build_cached.py', 'check-fast.py'} for arg in args):
                raise RuntimeError('Build/check/smoke process is active; cleanup postponed')
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--keep', type=int, default=3)
    parser.add_argument('--days', type=int, default=0)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.keep < 1 or args.days < 0:
        parser.error('--keep must be at least 1; --days cannot be negative')
    repo = Path(git(args.repo, 'rev-parse', '--show-toplevel')).resolve()
    state = state_dir(repo)
    config_file = state / 'config.json'
    config = json.loads(config_file.read_text(encoding='utf-8')) if config_file.exists() else {}
    with build_lock(state) as acquired:
        if not acquired:
            raise RuntimeError('Local build is active; cleanup postponed')
        refuse_active_builds()
        report = plan(repo, config, args.keep, args.days)
        report['mode'] = 'deleted' if args.apply else 'preview only'
        if args.apply:
            apply_plan(report)
            git(repo, 'worktree', 'prune')
        evidence = state / 'cleanup.json'
        evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('Preserved versions:', ', '.join(report['preserved_versions']))
        for reason in sorted({entry['reason'] for entry in report['files']}):
            items = [entry for entry in report['files'] if entry['reason'] == reason]
            print(f"{reason}: {len(items)} targets, {sum(item['bytes'] for item in items) / 1024**3:.2f} GiB")
        if report['skipped']:
            print('Skipped unsafe/unreadable targets:', len(report['skipped']))
        print(f"{report['mode']}: {len(report['files'])} targets, {report['bytes'] / 1024**3:.2f} GiB. Report: {evidence}")


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print('Cleanup refused:', error, file=sys.stderr)
        sys.exit(1)
