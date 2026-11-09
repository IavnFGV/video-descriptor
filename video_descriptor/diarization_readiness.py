"""Reuse real diarization proof only for unchanged model/runtime/backend inputs."""

import hashlib
import json
import os
import platform
import subprocess
from functools import lru_cache
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@lru_cache(maxsize=2)
def hardware(device):
    if device != 'xpu' or os.name != 'nt':
        return platform.machine()
    from .platform_support import windows_powershell, windows_shell_environment
    command = '[Console]::OutputEncoding=[Text.Encoding]::UTF8; ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_VideoController | Sort-Object PNPDeviceID | Select-Object Name,PNPDeviceID,DriverVersion)'
    try:
        result = subprocess.run([windows_powershell(), '-NoProfile', '-Command', command],
                                capture_output=True, encoding='utf-8-sig', timeout=10, check=True,
                                env=windows_shell_environment(), creationflags=0x08000000)
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def fingerprint(settings, here, profile):
    python = Path(settings.get('diarization_python') or '__missing__')
    model = Path(settings.get('diarization_model_directory') or '__missing__')
    device = settings.get('diarization_device', 'cpu')
    if not profile.get('revision') or device not in {'cpu', 'xpu'} or not python.is_file() or not (model / 'config.yaml').is_file():
        return None
    adapters = hardware('xpu' if settings.get('diarization_requested_device')=='auto' else device)
    if adapters is None:
        return None
    files = [python, model / 'config.yaml']
    files += [model / item['name'] for item in profile.get('files', [])]
    for directory in (python.parent, python.parent.parent):
        files += [path for path in (directory / 'pyvenv.cfg', directory / 'python312.dll') if path.is_file()]
        packages = directory / 'Lib/site-packages'
        for pattern in ['torch-*.dist-info/METADATA', 'pyannote_audio-*.dist-info/METADATA',
                        'torchaudio-*.dist-info/METADATA', 'torch/__init__.py', 'pyannote/audio/__init__.py']:
            files += list(packages.glob(pattern))
    try:
        inventory = [(str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns)
                     for path in sorted(set(files))]
        backend = {name: digest(here / name) for name in
                   ['diarization_worker.py', 'requirements-pyannote-' + device + '.lock']}
    except OSError:
        return None
    value = {'schema': 1, 'model': str(model.resolve()), 'revision': profile.get('revision'),
             'device': device,
             'system': platform.platform(), 'hardware': adapters, 'inventory': inventory, 'backend': backend}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def legacy_proof_matches(proof, settings, here, profile):
    """Adopt an existing real probe once, without requesting model access again."""
    device = settings.get('diarization_device', 'cpu')
    if (not isinstance(proof, dict) or not proof.get('turns') or proof.get('device') != device
            or not profile.get('revision') or proof.get('model_revision') != profile['revision']):
        return False
    try:
        if proof.get('requirements_sha256') != digest(here / ('requirements-pyannote-' + device + '.lock')):
            return False
        python = Path(settings['diarization_python'])
        for package, key in [('torch', 'torch'), ('pyannote_audio', 'pyannote')]:
            metadata = [path for directory in (python.parent, python.parent.parent)
                        for path in (directory / 'Lib/site-packages').glob(package + '-*.dist-info/METADATA')]
            if len(metadata) != 1:
                return False
            versions = [line.removeprefix('Version: ').strip() for line in metadata[0].read_text(encoding='utf-8').splitlines()
                        if line.startswith('Version: ')]
            if versions != [proof.get(key)]:
                return False
    except (OSError, KeyError):
        return False
    return True
