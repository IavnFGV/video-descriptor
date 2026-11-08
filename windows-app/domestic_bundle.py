"""Build-time allowlist for the private offline distribution. Never copy a venv."""
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

from build_release import HERE, resolved_wheels, safe_member, sha256, unpack_wheels


def copy_model(source, target, profile):
    source = Path(source)
    for item in profile['files']:
        name = safe_member(item['name'])
        path = source / name
        if path.stat().st_size != item['bytes']:
            raise ValueError('Model size mismatch: ' + str(name))
        if 'sha256' in item:
            valid = sha256(path) == item['sha256']
        else:
            payload = path.read_bytes()
            valid = hashlib.sha1(b'blob ' + str(len(payload)).encode() + b'\0' + payload).hexdigest() == item['git_blob']
        if not valid:
            raise ValueError('Model checksum mismatch: ' + str(name))
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)


def stage(folder, inputs_file, python_zip, cached_files=None):
    inputs = json.loads(Path(inputs_file).read_text(encoding='utf-8'))
    profile = json.loads((HERE / 'component-manifest.json').read_text(encoding='utf-8'))
    destination = folder / 'windows-app/domestic'
    copy_model(inputs['whisper_model'], destination / 'whisper', profile['whisper_model'])
    copy_model(inputs['diarization_model'], destination / 'diarization', profile['diarization_model'])
    wheels = resolved_wheels(Path(inputs['wheelhouse']), HERE / 'requirements-pyannote-cpu.lock')
    lock = json.loads((HERE / 'domestic-wheels.json').read_text(encoding='utf-8'))
    expected = {item['file']: item['sha256'] for item in lock}
    if {path.name for path in wheels} != set(expected):
        raise ValueError('Domestic wheel lock and requirements do not match')
    for path in wheels:
        if sha256(path) != expected[path.name]:
            raise ValueError('Domestic wheel checksum mismatch: ' + path.name)
    python = destination / 'python'
    python.mkdir()
    with zipfile.ZipFile(python_zip) as archive:
        for member in archive.infolist():
            safe_member(member.filename)
        archive.extractall(python)
    unpack_wheels(wheels, python / 'Lib/site-packages', cached_files)
    # Isolated embedded CPython is relocatable; machine-specific venv launchers are not.
    (python / 'python312._pth').write_text(
        'python312.zip\n.\nLib/site-packages\n../../..\n../..\nimport site\n', encoding='ascii')
    release = json.loads((HERE / 'release-inputs.json').read_text())
    for item in release['vcrt']['files']:
        source = folder / 'python' / item['name']
        shutil.copyfile(source, python / item['name'])
        library = python / 'Library/bin' / item['name']
        library.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, library)
    shutil.copyfile(folder / 'python/Microsoft-Visual-Cpp-LICENSE.rtf', python / 'Microsoft-Visual-Cpp-LICENSE.rtf')
    # Pin the exact same signed Fixed Runtime as the ordinary installer.
    definitions = (HERE / 'WebView2Runtime.iss').read_text()
    version = re.search(r'#define WebViewRuntimeVersion "([^"]+)"', definitions)[1]
    expected_cab = re.search(r'#define WebViewRuntimeSha256 "([^"]+)"', definitions)[1]
    cab = Path(inputs['webview_cab'])
    if sha256(cab) != expected_cab:
        raise ValueError('Domestic WebView2 checksum mismatch')
    shutil.copyfile(cab, destination / 'WebView2Runtime.x64.cab')
    for name in ('domestic_setup.py', 'Ensure-WebView2.ps1', 'domestic-wheels.json', 'DOMESTIC-NOTICES.md'):
        shutil.copyfile(HERE / name, folder / 'windows-app' / name)
    (folder / 'Prepare Domestic.cmd').write_text(
        '@echo off\r\n"%~dp0python\\python.exe" -X utf8 "%~dp0windows-app\\domestic_setup.py"\r\n'
        'if errorlevel 1 exit /b 1\r\n', encoding='ascii')
    (folder / 'Open Video Descriptor.cmd').write_text(
        '@echo off\r\ncall "%~dp0Prepare Domestic.cmd"\r\nif errorlevel 1 exit /b 1\r\n'
        'call "%~dp0windows-app\\Open-App.cmd"\r\n', encoding='ascii')
    # No absolute builder paths or credentials in provenance.
    return {'whisper_revision': profile['whisper_model']['revision'],
            'diarization_revision': profile['diarization_model']['revision'],
            'diarization_device': 'cpu', 'wheels': lock,
            'webview_version': version, 'webview_sha256': expected_cab,
            'optional': ['ollama', 'translation_model', 'notes_model', 'xpu_diarization']}
