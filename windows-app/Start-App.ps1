param([switch]$NoBrowser, [switch]$StartNpu, [switch]$Doctor, [switch]$Stop)
$ErrorActionPreference = 'Stop'
$appDirectory = $PSScriptRoot
$projectDirectory = Split-Path -Parent $appDirectory
$pythonPath = Join-Path $projectDirectory '.venv-windows\Scripts\python.exe'
if (Test-Path -LiteralPath (Join-Path $projectDirectory 'python\python.exe')) { $pythonPath = Join-Path $projectDirectory 'python\python.exe' }
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run windows-app\Install-App.ps1 first. The NPU environment is separate.' }
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$appPath = Join-Path $appDirectory 'app.py'
if ($Doctor) { & $pythonPath -X utf8 $appPath --doctor; exit $LASTEXITCODE }
if ($Stop) { & $pythonPath -X utf8 $appPath --stop; exit $LASTEXITCODE }
$settings = Get-Content -LiteralPath (Join-Path $appDirectory 'config.example.json') -Raw | ConvertFrom-Json
$localPath = Join-Path $appDirectory 'config.local.json'
if (Test-Path -LiteralPath $localPath) { $localSettings = Get-Content -LiteralPath $localPath -Raw | ConvertFrom-Json; foreach ($property in $localSettings.PSObject.Properties) { $settings.($property.Name) = $property.Value } }
$url = 'http://127.0.0.1:' + $settings.port
$expectedWorkspace = [IO.Path]::GetFullPath((Join-Path $appDirectory $settings.workspace))
$logsPath = Join-Path $appDirectory 'runtime\logs'
New-Item -ItemType Directory -Path $logsPath -Force | Out-Null
$launchId = [guid]::NewGuid().ToString('N')
$launchOutput = Join-Path $logsPath ($launchId + '.stdout.log')
$launchError = Join-Path $logsPath ($launchId + '.stderr.log')
$arguments = '-X utf8 -u "' + $appPath + '"'
if ($NoBrowser) { $arguments += ' --no-browser' }
if ($StartNpu) { $arguments += ' --start-npu' }
$process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $projectDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput $launchOutput -RedirectStandardError $launchError
$ready = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri ($url + '/health') -TimeoutSec 1
        if ($health.app -eq 'video-descriptor-windows' -and $health.workspace -eq $expectedWorkspace) { $ready = $true; break }
    } catch { }
    $process.Refresh()
    if ($process.HasExited -and $process.ExitCode -ne 0) { break }
    Start-Sleep -Milliseconds 250
}
if (-not $ready) {
    if (Test-Path -LiteralPath $launchError) { Get-Content -LiteralPath $launchError -Encoding UTF8 }
    throw ('Application did not become ready. See ' + $logsPath)
}
Write-Output ('Ready: ' + $url)
