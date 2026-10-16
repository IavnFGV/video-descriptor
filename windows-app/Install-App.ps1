param([switch]$CreateShortcut)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectDirectory '.venv-windows\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    & python -X utf8 -m venv (Join-Path $projectDirectory '.venv-windows')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required. No system components were installed.' }
}
Write-Output 'Installing application packages into .venv-windows only; no AI models, drivers, WSL or Docker.'
& $pythonPath -X utf8 -m pip install -r (Join-Path $PSScriptRoot 'requirements-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; NPU environment was not changed.' }
& $pythonPath -X utf8 -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
if ($CreateShortcut) {
    $desktopDirectory = [Environment]::GetFolderPath('Desktop')
    $shortcutPath = Join-Path $desktopDirectory 'Video Descriptor.lnk'
    if (Test-Path -LiteralPath $shortcutPath) { throw 'Shortcut already exists; it was not overwritten.' }
    $runtimeDirectory = Join-Path $PSScriptRoot 'runtime'
    New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
    # Some Windows Script Host setups cannot save directly to a localized OneDrive path.
    $stagedShortcutPath = Join-Path $runtimeDirectory 'Video Descriptor.lnk'
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($stagedShortcutPath)
    $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $shortcut.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $PSScriptRoot 'Start-App.ps1') + '"'
    $shortcut.WorkingDirectory = $projectDirectory
    $shortcut.Description = 'Video Descriptor - local transcription'
    $shortcut.Save()
    Copy-Item -LiteralPath $stagedShortcutPath -Destination $shortcutPath -ErrorAction Stop
    Write-Output ('Created: ' + $shortcutPath)
}
Write-Output 'Ready. Open windows-app\Open-App.cmd.'
