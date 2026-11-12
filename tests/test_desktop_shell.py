"""Desktop shell contracts: one unified window, native recovery, tray and exit.

The static contracts always run. The compiled harness additionally runs the real
WinForms host on Windows when the pinned WebView2 SDK and the system C# compiler
are available; it is skipped instead of faked when they are not.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / 'windows-app' / 'DesktopHost.cs'
HARNESS = Path(__file__).resolve().parent / 'desktop' / 'DesktopShellHarness.cs'
SDK = ROOT / 'windows-app' / 'runtime' / 'desktop-sdk'
COMPILER = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319' / 'csc.exe'
FRAMEWORK = ('System.Windows.Forms.dll', 'System.Drawing.dll', 'System.Web.Extensions.dll', 'System.Net.Http.dll')
LIBRARIES = ('Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll')


def host_source():
    return HOST.read_text(encoding='utf-8')


def test_native_toolbar_and_duplicate_navigation_are_removed():
    text = host_source()
    assert 'Главная' not in text
    assert 'FlowLayoutPanel' not in text
    assert 'DockStyle.Top' not in text
    assert 'var bar' not in text and 'var home' not in text


def test_webview_owns_the_whole_client_area():
    text = host_source()
    assert 'web.Dock = DockStyle.Fill; web.Visible = false;' in text
    assert 'Controls.Add(web); Controls.Add(fallback);' in text
    assert 'fallback.Dock = DockStyle.Fill; fallback.Visible = false;' in text
    # The standard window frame, dragging and resizing stay untouched.
    assert 'FormBorderStyle' not in text
    assert 'Size = new Size(1200, 820); MinimumSize = new Size(760, 560);' in text


def test_native_fallback_owns_the_retry_button():
    text = host_source()
    assert 'retry.Text = "Подключиться снова"; retry.AutoSize = true;' in text
    assert 'fallback.Controls.Add(status, 0, 0);' in text
    assert 'fallback.Controls.Add(retry, 0, 1);' in text
    assert 'retry.Click += async delegate { await Connect(); };' in text
    # The fallback is native and stays available without WebView2 or a backend.
    assert 'fallback.Visible = true; status.Visible = true;' in text
    assert 'web.Visible = false; fallback.Visible = true; status.Visible = true;' in text
    assert 'retry.Enabled = true;' in text
    assert 'Логи: ' in text and 'runtime' in text


def test_tray_close_to_tray_and_single_instance_are_preserved():
    text = host_source()
    assert 'if (!quitting && e.CloseReason == CloseReason.UserClosing) { e.Cancel = true; Hide(); }' in text
    assert 'menu.Items.Add("Открыть", null, delegate { Restore(); });' in text
    assert 'menu.Items.Add("Завершить приложение", null, async delegate { await Quit(); });' in text
    assert 'tray.DoubleClick += delegate { Restore(); };' in text
    assert r'Local\\VideoDescriptor-' in text
    assert r'Local\\VideoDescriptorShow-' in text


def test_health_monitoring_and_active_job_protection_are_preserved():
    text = host_source()
    assert 'await Health();' in text
    assert 'Соединение с backend потеряно. ' in text
    assert '"/api/native/stop"' in text
    assert 'HttpStatusCode.Conflict' in text
    assert 'if (response.StatusCode == HttpStatusCode.Conflict) {' in text
    assert 'Обработка ещё выполняется.' in text


def test_webview_security_restrictions_are_preserved():
    text = host_source()
    for setting in ('AreHostObjectsAllowed = false', 'IsWebMessageEnabled = false', 'AreDevToolsEnabled = false',
                    'AreBrowserAcceleratorKeysEnabled = false', 'AreDefaultContextMenusEnabled = false'):
        assert setting in text
    assert 'CoreWebView2PermissionState.Deny' in text
    assert 'AddHostObjectToScript' not in text
    assert 'PostWebMessageAsJson' not in text


def test_desktop_smoke_contracts_are_preserved():
    text = host_source()
    for fragment in ('UI document is empty', 'AI setup DOM or handlers missing', 'Active queue was not protected',
                     'Close did not hide to tray', 'Second window was not suppressed',
                     'Repeated launch did not restore window', 'Backend loss did not show an error screen',
                     'Error screen did not offer a native retry', 'Retry did not restore WebView'):
        assert fragment in text
    assert 'RequireClientArea();' in text


def compile_source(source, output, target, extra=()):
    command = [str(COMPILER), '/nologo', f'/target:{target}', '/codepage:65001', f'/out:{output}']
    references = [str(SDK / name) for name in LIBRARIES]
    references += [str(COMPILER.parent / name) for name in FRAMEWORK]
    references += [str(item) for item in extra]
    for reference in references:
        command.append(f'/reference:{reference}')
    command.append(str(source))
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.name != 'nt', reason='Windows WinForms desktop host')
def test_compiled_host_is_one_unified_window(tmp_path):
    if not COMPILER.is_file():
        pytest.skip('System C# compiler is unavailable')
    if not all((SDK / name).is_file() for name in LIBRARIES):
        pytest.skip('WebView2 SDK is not prepared; run windows-app/Prepare-Desktop.ps1')
    build = tmp_path / 'build'
    build.mkdir()
    host = build / 'VideoDescriptor.DesktopHost.dll'
    compile_source(HOST, host, 'library')
    harness = build / 'DesktopShellHarness.exe'
    compile_source(HARNESS, harness, 'exe', extra=[host])
    for name in LIBRARIES + ('WebView2Loader.dll',):
        library = SDK / name
        if library.is_file():
            shutil.copyfile(library, build / name)
    result = subprocess.run([str(harness), str(ROOT / 'windows-app')], check=False, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'desktop shell harness passed' in result.stdout
