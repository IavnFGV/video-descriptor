param(
    [Parameter(Mandatory=$true)][string]$ModelDirectory,
    [ValidateSet('cpu','xpu')][string]$Device = 'cpu',
    [string]$PythonPath,
    [switch]$InstallDependencies
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $ModelDirectory 'config.yaml'))) { throw 'Укажите существующую локальную модель pyannote community-1. Модели автоматически не скачиваются.' }
if (-not $PythonPath) { $PythonPath = Join-Path $root '.venv-diarization\Scripts\python.exe' }
if ($InstallDependencies) {
    if ($Device -ne 'cpu') { throw 'Для Intel GPU подготовьте отдельный Python с PyTorch XPU и передайте -PythonPath. Автоматической подмены CPU нет.' }
    if (-not (Test-Path -LiteralPath $PythonPath)) { & python -m venv (Join-Path $root '.venv-diarization'); if ($LASTEXITCODE) { throw 'Не удалось создать окружение диаризации.' } }
    & $PythonPath -m pip install -r (Join-Path $root 'requirements-diarization.txt')
    if ($LASTEXITCODE) { throw 'Не удалось установить зависимости диаризации.' }
}
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Окружение не найдено. Укажите -PythonPath или явно добавьте -InstallDependencies.' }
& $PythonPath -X utf8 (Join-Path $PSScriptRoot 'diarization_worker.py') --doctor --model $ModelDirectory --device $Device
if ($LASTEXITCODE) { throw 'Проверка диаризации не прошла. Настройки приложения не изменены.' }
$local = Join-Path $PSScriptRoot 'config.local.json'
$settings = @{}
if (Test-Path -LiteralPath $local) { $document = Get-Content -LiteralPath $local -Raw | ConvertFrom-Json; foreach ($property in $document.PSObject.Properties) { $settings[$property.Name] = $property.Value } }
$settings['diarization_python'] = (Resolve-Path -LiteralPath $PythonPath).Path
$settings['diarization_model_directory'] = (Resolve-Path -LiteralPath $ModelDirectory).Path
$settings['diarization_device'] = $Device
[System.IO.File]::WriteAllText($local, ($settings | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
Write-Output 'Диаризация настроена. Перезапустите приложение после завершения очереди. Docker не требуется.'
