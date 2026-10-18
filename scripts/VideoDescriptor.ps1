#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Install', 'Start', 'Stop', 'Update', 'Logs', 'Status', 'Uninstall')]
    [string]$Action = 'Install',
    [string]$Image,
    [int]$ReadyTimeout = 180
)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$dockerHelp = 'https://docs.docker.com/desktop/setup/install/windows-install/'
function Invoke-Compose {
    & docker compose --project-directory $project @args
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed ($LASTEXITCODE). See Docker Desktop and the Logs command." }
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is required to supply Python, FFmpeg and OCR. Install it with the WSL 2 backend: $dockerHelp"
}
& docker compose version | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Docker Compose v2 is required. Update Docker Desktop: $dockerHelp" }
$engineMessage = 'Start Docker Desktop, select Linux containers and enable Settings > General > Use the WSL 2 based engine. Then retry.'
try { $engine = & docker info --format '{{.OSType}}' 2>$null }
catch { throw $engineMessage }
if ($LASTEXITCODE -ne 0) { throw $engineMessage }
if ($engine -ne 'linux') { throw 'Switch Docker Desktop to Linux containers with the WSL 2 backend.' }
if ($Action -in @('Install', 'Start', 'Update')) {
    if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) {
        throw 'WSL 2 is required. Follow https://learn.microsoft.com/windows/wsl/install and restart Windows if requested. This script does not change system features.'
    }
    try { $distros = ((& wsl --list --verbose 2>&1) -join "`n") -replace "`0", '' }
    catch { throw 'WSL is unavailable. Follow https://learn.microsoft.com/windows/wsl/install and retry after the required restart.' }
    if ($LASTEXITCODE -ne 0 -or $distros -notmatch '(?m)\s2\s*$') {
        throw 'No WSL 2 distribution found. Check wsl --list --verbose and Docker Desktop WSL 2 settings: https://docs.docker.com/desktop/features/wsl/'
    }
    $kernel = & docker info --format '{{.KernelVersion}}'
    if ($LASTEXITCODE -ne 0 -or $kernel -notmatch '(?i)microsoft|wsl') {
        throw 'The active Docker Engine is not using WSL 2. Select the local Docker Desktop context and enable its WSL 2 backend.'
    }
}
$config = Join-Path $project '.env'
if (-not (Test-Path -LiteralPath $config)) {
    Copy-Item -LiteralPath (Join-Path $project '.env.example') -Destination $config
}
if (-not $Image -and $Action -eq 'Install' -and (Test-Path -LiteralPath (Join-Path $project 'VERSION'))) {
    $version = (Get-Content -LiteralPath (Join-Path $project 'VERSION') -Raw).Trim()
    if ($version -notmatch '^v\d+\.\d+\.\d+$') { throw 'Invalid release VERSION' }
    $Image = "ghcr.io/iavnfgv/video-descriptor:$version"
}
if ($Image) {
    if ($Image -notmatch '^ghcr\.io/iavnfgv/video-descriptor:(v\d+\.\d+\.\d+|sha-[a-f0-9]+)$') {
        throw 'Use a versioned ghcr.io/iavnfgv/video-descriptor:vX.Y.Z image.'
    }
    $lines = @(Get-Content -LiteralPath $config | Where-Object { $_ -notmatch '^VIDEO_DESCRIPTOR_IMAGE=' })
    $lines += "VIDEO_DESCRIPTOR_IMAGE=$Image"
    [IO.File]::WriteAllLines($config, $lines, [Text.UTF8Encoding]::new($false))
}
# Capture internally: resolved config can contain API keys; never print it.
$resolved = & docker compose --project-directory $project config --format json
if ($LASTEXITCODE -ne 0) { throw 'Invalid Compose configuration. Check .env.' }
$service = ($resolved | ConvertFrom-Json).services.app
$workspace = @($service.volumes | Where-Object { $_.target -eq '/workspace' })[0].source
foreach ($folder in @('data', 'output', '.devcontainer', 'cache')) {
    New-Item -ItemType Directory -Path (Join-Path $workspace $folder) -Force | Out-Null
}
switch ($Action) {
    'Stop' { Invoke-Compose stop; return }
    'Uninstall' {
        Invoke-Compose down
        Write-Host "Containers removed. Data and configuration preserved: $workspace ; $config"
        return
    }
    'Logs' { Invoke-Compose logs --tail 100 --follow app; return }
    'Status' { Invoke-Compose ps; return }
}
if ($service.image -eq 'video-descriptor:local') {
    if (-not (Test-Path -LiteralPath (Join-Path $project 'Dockerfile'))) {
        throw 'This bundle needs a published image. Pass -Image ghcr.io/iavnfgv/video-descriptor:vX.Y.Z.'
    }
    if ($Action -in @('Install', 'Update')) { Invoke-Compose build --pull app }
} else {
    if ($Action -in @('Install', 'Update')) { Invoke-Compose pull app }
}
Invoke-Compose up -d --no-build --wait --wait-timeout $ReadyTimeout app
$port = @($service.ports)[0].published
$url = "http://localhost:$port"
$health = Invoke-RestMethod -Uri "$url/health" -TimeoutSec 5
if ($health.status -ne 'ok') { throw 'HTTP readiness failed. Run the Logs command.' }
Write-Host "Ready: $url/create"
Write-Host "Data: $workspace"
Write-Host 'CPU Whisper downloads its model on the first recognition job, not during installation.'
Write-Host "Connections: $url/api/diagnostics (Ollama/Gemini are optional for CPU transcription)."
Write-Host 'Commands: .\scripts\VideoDescriptor.ps1 -Action Start|Stop|Update|Logs|Status|Uninstall'
Write-Host 'Published updates: -Action Update -Image ghcr.io/iavnfgv/video-descriptor:vX.Y.Z'
