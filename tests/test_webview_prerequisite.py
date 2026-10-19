import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Real Windows Authenticode verification')
@pytest.mark.parametrize('exists', [True, False])
def test_webview_prerequisite_rejects_unsigned_or_missing_download(tmp_path, exists):
    installer = tmp_path / 'untrusted.exe'
    if exists:
        installer.write_bytes(b'Not a signed Microsoft executable')
    log = tmp_path / 'verification.jsonl'
    script = Path(__file__).resolve().parents[1] / 'windows-app/Ensure-WebView2.ps1'
    result = subprocess.run([
        'powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', str(script), '-Mode', 'Verify', '-LoaderPath', str(tmp_path / 'unused.dll'),
        '-InstallerPath', str(installer), '-LogPath', str(log),
    ], check=False, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stderr
    events = [json.loads(line) for line in log.read_text(encoding='utf-8-sig').splitlines()]
    assert events[-1]['event'] == 'error'
    assert not any(event['event'] in {'installer_exit', 'ready'} for event in events)
    if exists:
        verification = next(event for event in events if event['event'] == 'installer_verification')
        assert verification['details']['status'] != 'Valid'
        assert len(verification['details']['sha256']) == 64
