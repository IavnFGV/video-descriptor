"""Regression for Windows extended paths and pip's relative scripts scheme."""
import csv
import io
import ntpath
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows-app'))
from install_packages import normalize_record_path


@pytest.mark.parametrize('prefix', [r'C:\AI', r'\\?\C:\Users\Пользователь\AI', r'\\?\UNC\server\share\AI'])
def test_record_lookup_collapses_relative_script_path_and_preserves_prefix(prefix):
    normalized = normalize_record_path(prefix + r'\Lib\site-packages\..\..\Scripts\readelf.py')
    assert normalized == prefix + r'\Scripts\readelf.py'
    assert normalize_record_path(normalized) == normalized


@pytest.mark.skipif(os.name != 'nt', reason='Windows extended-path wheel installation')
def test_install_wheel_with_script_into_long_extended_prefix(tmp_path):
    prefix = tmp_path / 'Окружение с пробелами' / ('a' * 80) / ('b' * 80)
    files = {
        'vd_path_probe/__init__.py': b'',
        'vd_path_probe-1.0.data/scripts/readelf.py': b'#!python\nprint("probe")\n',
        'vd_path_probe-1.0.dist-info/METADATA': b'Metadata-Version: 2.1\nName: vd-path-probe\nVersion: 1.0\n',
        'vd_path_probe-1.0.dist-info/WHEEL': b'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
    }
    record = 'vd_path_probe-1.0.dist-info/RECORD'
    buffer = io.StringIO()
    csv.writer(buffer).writerows((name, '', '') for name in [*files, record])
    files[record] = buffer.getvalue().encode()
    wheel = tmp_path / 'vd_path_probe-1.0-py3-none-any.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    extended = '\\\\?\\' + str(prefix.resolve())
    installer = Path(__file__).resolve().parents[1] / 'windows-app/install_packages.py'
    result = subprocess.run([sys.executable, str(installer), '--isolated', 'install', '--no-index', '--no-deps',
                             '--ignore-installed', '--prefix', extended, str(wheel)], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    script = Path(ntpath.join(extended, 'Scripts', 'readelf.py'))
    assert script.is_file()
    assert 'probe' in script.read_text()
