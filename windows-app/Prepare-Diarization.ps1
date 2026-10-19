param(
    [Parameter(Mandatory=$true)][string]$ModelDirectory,
    [ValidateSet('auto','cpu','xpu')][string]$Device = 'auto',
    [string]$PythonPath,
    [string]$ProbeAudio,
    [switch]$InstallDependencies,
    [switch]$PlanOnly
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$bootstrap = Join-Path $root '.venv-windows\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $bootstrap)) {
    if ($PythonPath -and (Test-Path -LiteralPath $PythonPath)) { $bootstrap = $PythonPath } else { $bootstrap = 'python' }
}
$setupArguments = @('-X', 'utf8', (Join-Path $PSScriptRoot 'diarization_setup.py'), '--model', $ModelDirectory, '--device', $Device)
if ($PythonPath) { $setupArguments += @('--python', $PythonPath) }
if ($ProbeAudio) { $setupArguments += @('--probe-audio', $ProbeAudio) }
if ($InstallDependencies) { $setupArguments += '--install' }
if ($PlanOnly) { $setupArguments += '--plan-only' }
& $bootstrap @setupArguments
if ($LASTEXITCODE) { throw 'Diarization preparation failed. Existing application settings were preserved.' }
