"""Read-only verification of the WSL snapshot; does not load models or run jobs."""
import hashlib
import json
import subprocess
from pathlib import Path

SOURCE = Path(r"\\wsl.localhost\Ubuntu\home\ivand\projects\video-descriptor")
DESTINATION = Path(__file__).resolve().parent.parent
EXCLUDE = {".venv", ".venv-diarization", ".venv-diarization-xpu",
           "__pycache__", ".pytest_cache", ".ruff_cache"}
LINKS = {
    "output/2026-10-05 12-06-24-974d8f1e49/run.log":
        "output/2026-10-05 12-06-24-974d8f1e49/translation-markers.log",
    "output/2026-10-09 11-06-54-40be94a81a/run.log": "output/new-video.log",
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    records, errors = [], []
    # Hash inside WSL: reading gigabytes through the UNC bridge is very slow.
    source_code = '''
import os, hashlib, json
from pathlib import Path
root = Path('/home/ivand/projects/video-descriptor')
exclude = set(EXCLUSIONS)
records = []
for folder, dirs, names in os.walk(root):
    dirs[:] = [name for name in dirs if name not in exclude]
    for name in names:
        path = Path(folder) / name
        with path.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        records.append({'path': path.relative_to(root).as_posix(),
                        'bytes': path.stat().st_size, 'sha256': checksum})
print(json.dumps(records))
'''.replace('EXCLUSIONS', repr(sorted(EXCLUDE)))
    result = subprocess.run(['wsl', '-d', 'Ubuntu', '--', 'python3', '-c', source_code],
                            capture_output=True, text=True, encoding='utf-8', check=True)
    for record in json.loads(result.stdout):
        name = record['path']
        # WSL's SMB bridge encodes the colon in the old :memory:.ses filename.
        target = DESTINATION / name.replace(':', '\uf03a')
        try:
            target_hash = digest(target)
            if record['sha256'] != target_hash:
                errors.append({"path": name, "error": "SHA256 mismatch"})
            records.append(record)
        except OSError as exc:
            errors.append({"path": name, "error": str(exc)})
    report = {"source": str(SOURCE), "destination": str(DESTINATION),
              "excluded_directory_names": sorted(EXCLUDE),
              "materialized_log_links": LINKS, "files": len(records),
              "bytes": sum(item["bytes"] for item in records),
              "errors": errors, "manifest": records}
    (Path(__file__).parent / "copy-verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("files", "bytes", "errors")}))
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
