param([switch]$Verify, [switch]$Smoke, [string]$PythonPath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms,System.Drawing,System.Web.Extensions,System.Net.Http
try {
    $sdk = Join-Path $PSScriptRoot 'desktop-sdk'
    if (-not (Test-Path -LiteralPath $sdk)) { $sdk = Join-Path $PSScriptRoot 'runtime\desktop-sdk' }
    if (-not (Test-Path -LiteralPath (Join-Path $sdk 'WebView2Loader.dll'))) {
        throw 'Desktop libraries are missing. Run windows-app\Prepare-Desktop.ps1 or reinstall the preview.'
    }
    $env:PATH = $sdk + ';' + $env:PATH
    if (-not $Verify -and -not $Smoke) {
        $executable = Join-Path $sdk 'VideoDescriptor.exe'
        if (-not (Test-Path -LiteralPath $executable)) { throw 'Desktop executable is missing. Reinstall the preview or run Prepare-Desktop.ps1.' }
        $launchArguments = '"' + $PSScriptRoot + '"'
        if ($PythonPath) { $launchArguments += ' "' + $PythonPath + '"' }
        # This is the requested visible application window, not a background helper.
        Start-Process -FilePath $executable -ArgumentList $launchArguments -WindowStyle Normal | Out-Null
        exit 0
    }
    $core = Join-Path $sdk 'Microsoft.Web.WebView2.Core.dll'
    $forms = Join-Path $sdk 'Microsoft.Web.WebView2.WinForms.dll'
    Add-Type -Path $core,$forms
    Add-Type -Path (Join-Path $PSScriptRoot 'DesktopHost.cs') -ReferencedAssemblies @($core,$forms,'System.Windows.Forms','System.Drawing','System.Web.Extensions','System.Net.Http')
    if ($Verify) { [VideoDescriptor.DesktopHost]::Verify(); exit 0 }
    $root = Split-Path -Parent $PSScriptRoot
    $python = Join-Path $root 'python\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { $python = Join-Path $root '.venv-windows\Scripts\python.exe' }
    if ($PythonPath) { $python = $PythonPath }
    if (-not (Test-Path -LiteralPath $python)) { throw 'Application Python runtime is missing. Reinstall the preview.' }
    [VideoDescriptor.DesktopHost]::Run($python, $PSScriptRoot, [bool]$Smoke)
} catch {
    if ($Verify -or $Smoke) { throw }
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Video Descriptor - startup error', 'OK', 'Error') | Out-Null
    exit 1
}
