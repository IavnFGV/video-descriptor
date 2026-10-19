"""Harness regression checks. These are host unit tests, not acceptance evidence."""
import importlib.util
import json
import os
import shutil
import socket
import struct
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / 'windows-app/sandbox'
PS = shutil.which('powershell.exe') if os.name == 'nt' else None
spec = importlib.util.spec_from_file_location('sandbox_acceptance_ui', SANDBOX / 'acceptance_ui.py')
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


def ps_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def powershell(script, *, check=True):
    if not PS:
        pytest.skip('Windows PowerShell 5.1 required')
    command = f". {ps_string(SANDBOX / 'Acceptance.Common.ps1')}; {script}"
    # A Python child inherits PowerShell 7's module search path verbatim; let 5.1
    # build its own path instead of loading incompatible Core modules.
    environment = {key: value for key, value in os.environ.items() if key.upper() != 'PSMODULEPATH'}
    return subprocess.run([PS, '-NoProfile', '-NonInteractive', '-Command', command],
                          capture_output=True, text=True, timeout=30, check=check, env=environment)


def test_dependency_plan_does_not_download_whisper_for_ollama():
    stages = powershell("ConvertTo-Json @(Get-StageClosure @('ollama-inference'))").stdout
    assert json.loads(stages) == ['preflight', 'installer', 'desktop', 'ollama-install',
                                 'ollama-model', 'ollama-inference']
    translation = powershell("ConvertTo-Json @(Get-StageClosure @('translation'))").stdout
    assert 'whisper' in json.loads(translation)


def test_canonical_hash_survives_json_roundtrip_and_key_order():
    result = powershell("""
    $a=@{z=@(@{c=3;a=1});b=2}
    $b='{"b":2,"z":[{"a":1,"c":3}]}' | ConvertFrom-Json
    if ((Get-TextHash (ConvertTo-CanonicalJson $a)) -ne (Get-TextHash (ConvertTo-CanonicalJson $b))) { throw 'unstable fingerprint' }
    """)
    assert result.returncode == 0


@pytest.mark.parametrize('member', ['../outside.txt', r'..\outside.txt', r'C:\outside.txt'])
def test_cache_cannot_escape_root(tmp_path, member):
    result = powershell(f'Get-ContainedPath {ps_string(tmp_path)} {ps_string(member)}', check=False)
    assert result.returncode != 0


def test_corrupted_cache_rejected(tmp_path):
    fixture = tmp_path / 'test.bin'
    fixture.write_bytes(b'original')
    script = f"""
    $root={ps_string(tmp_path)}
    $file=@{{file='test.bin';bytes=8;sha256=(Get-FileHash -LiteralPath (Join-Path $root 'test.bin')).Hash.ToLowerInvariant()}}
    Test-ObjectFiles $root @($file)
    [IO.File]::WriteAllText((Join-Path $root 'test.bin'),'modified')
    Test-ObjectFiles $root @($file)
    """
    result = powershell(script, check=False)
    assert result.returncode != 0
    assert 'Integrity mismatch' in result.stderr


def test_bootstrap_refuses_host_before_writing_reports():
    result = powershell(f'& {ps_string(SANDBOX / "Bootstrap-Acceptance.ps1")}', check=False)
    assert result.returncode != 0
    assert 'REFUSED' in result.stderr


def test_cleanup_preserves_live_runs_reports_and_cache(tmp_path):
    runs = tmp_path / 'runs'
    for name, status in [('complete', 'PASS'), ('active', 'RUNNING'), ('waiting', 'PREPARED')]:
        root = runs / name
        (root / 'input').mkdir(parents=True)
        (root / 'reports').mkdir()
        (root / 'input/artifact.bin').write_bytes(b'x')
        (root / 'reports/report.json').write_text(json.dumps({'profile': 'Security', 'status': status}))
    cached = tmp_path / 'cache/private.bin'
    cached.parent.mkdir()
    cached.write_bytes(b'preserve')
    powershell(f'& {ps_string(SANDBOX / "Run-Acceptance.ps1")} -Action Clean -RunsDirectory {ps_string(runs)}')
    assert not (runs / 'complete/input').exists()
    assert (runs / 'complete/reports/report.json').exists()
    assert (runs / 'active/input/artifact.bin').exists()
    assert (runs / 'waiting/input/artifact.bin').exists()
    assert cached.read_bytes() == b'preserve'


def test_contract_dependencies_match_runtime():
    contracts = json.loads((SANDBOX / 'stage-contracts.json').read_text())
    runtime = json.loads(powershell('$StageDependencies | ConvertTo-Json -Depth 5').stdout)
    assert {stage['name']: stage['dependencies'] for stage in contracts['stages']} == runtime


def test_devtools_refuses_external_endpoint():
    with pytest.raises(ValueError, match='loopback'):
        ui.CDP('ws://example.com:9222/devtools/page/1')


def test_websocket_client_masks_frames():
    client, peer = socket.socketpair()
    driver = ui.CDP.__new__(ui.CDP)
    driver.sock = client
    try:
        driver.send(b'synthetic prompt')
        frame = peer.recv(1024)
        assert frame[0] == 0x81 and frame[1] & 0x80
        length = frame[1] & 0x7f
        mask = frame[2:6]
        decoded = bytes(value ^ mask[index % 4] for index, value in enumerate(frame[6:]))
        assert length == len(decoded) and decoded == b'synthetic prompt'
    finally:
        client.close()
        peer.close()


def test_websocket_fragmentation_and_ping():
    client, peer = socket.socketpair()
    driver = ui.CDP.__new__(ui.CDP)
    driver.sock = client
    try:
        payload = b'{"id":1,"result":{"value":"synthetic"}}'
        peer.sendall(b'\x01\x0a' + payload[:10] + b'\x89\x01?' + bytes([0x80, len(payload)-10]) + payload[10:])
        assert driver.receive() == json.loads(payload)
        assert peer.recv(1024)[0] == 0x8a
    finally:
        client.close()
        peer.close()


def test_websocket_rejects_oversized_frames():
    client, peer = socket.socketpair()
    driver = ui.CDP.__new__(ui.CDP)
    driver.sock = client
    try:
        peer.sendall(b'\x81\x7f' + struct.pack('!Q', 100 * 1024 * 1024))
        with pytest.raises(ValueError, match='Invalid DevTools frame'):
            driver.receive()
    finally:
        client.close()
        peer.close()
