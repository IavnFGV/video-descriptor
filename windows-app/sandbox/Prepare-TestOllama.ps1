param(
    [Parameter(Mandatory)][string]$CacheDirectory,
    [switch]$DownloadOnly,
    [string]$TargetDirectory,
    [string]$ModelDirectory,
    [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,150}$')][string]$Model='qwen3.5:0.8b',
    [ValidatePattern('^127\.0\.0\.1:[0-9]{4,5}$')][string]$HostAddress='127.0.0.1:11434',
    [string]$ReportPath
)
. "$PSScriptRoot\Acceptance.Common.ps1"
$ollamaInput=Read-Json (Join-Path $PSScriptRoot 'ollama-test-input.json')
New-Item -ItemType Directory -Path $CacheDirectory -Force | Out-Null
$installer=Join-Path (Resolve-Path $CacheDirectory) ('OllamaSetup-'+$ollamaInput.version+'.exe')
if (!(Test-Path -LiteralPath $installer)) {
    $partial=$installer+'.partial'
    $curl=Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source --fail --location --silent --show-error --retry 2 --connect-timeout 20 --max-time 1800 --continue-at - --output $partial $ollamaInput.url
        if ($LASTEXITCODE -ne 0) { throw 'Pinned Ollama installer download failed; partial bytes retained for resume' }
    } else {
        $ProgressPreference='SilentlyContinue'
        Invoke-WebRequest -Uri $ollamaInput.url -OutFile $partial -UseBasicParsing -TimeoutSec 1800
    }
    Move-Item -LiteralPath $partial -Destination $installer
}
Test-ObjectFiles (Split-Path $installer) @(@{file=(Split-Path $installer -Leaf);bytes=$ollamaInput.bytes;sha256=$ollamaInput.sha256})
$signature=Get-AuthenticodeSignature -LiteralPath $installer
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch $ollamaInput.publisher_pattern) { throw 'Ollama installer signature/publisher verification failed' }
if ($DownloadOnly) { Write-Output $installer;return }
if ($env:GITHUB_ACTIONS -ne 'true' -and $env:USERNAME -ne 'WDAGUtilityAccount') { throw 'Installation is restricted to CI/disposable Sandbox. Use -DownloadOnly on the development host.' }
if (!$TargetDirectory -or !$ModelDirectory -or !$ReportPath) { throw 'TargetDirectory, ModelDirectory and ReportPath are required for installation' }
if (Test-Path -LiteralPath $TargetDirectory) { throw 'Use a fresh isolated Ollama installation target' }
$port=[int]($HostAddress.Split(':')[1])
if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { throw 'Requested test port is already occupied; no service was stopped' }
New-Item -ItemType Directory -Path (Split-Path $ReportPath),$ModelDirectory -Force | Out-Null
$env:OLLAMA_HOST=$HostAddress;$env:OLLAMA_MODELS=[IO.Path]::GetFullPath($ModelDirectory);$env:OLLAMA_NO_CLOUD='1'
$p=Start-Process -FilePath $installer -ArgumentList ('/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /TASKS= /DIR="'+[IO.Path]::GetFullPath($TargetDirectory)+'" /LOG="'+$ReportPath+'.install.log"') -PassThru -WindowStyle Hidden
$null=$p.Handle
if (!$p.WaitForExit(600000)) { throw 'Ollama installer timed out' }
$p.WaitForExit();$p.Refresh();if ($p.ExitCode -ne 0) { throw ('Ollama installer failed: '+$p.ExitCode) }
$exe=Join-Path $TargetDirectory 'ollama.exe'
$listener=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $server=Get-Process -Id $listener.OwningProcess
    if (!$server.Path.StartsWith([IO.Path]::GetFullPath($TargetDirectory).TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'The test port was acquired by a different application' }
} else {
    $server=Start-Process -FilePath $exe -ArgumentList 'serve' -PassThru -WindowStyle Hidden -RedirectStandardOutput ($ReportPath+'.server.log') -RedirectStandardError ($ReportPath+'.server.stderr.log')
}
$deadline=(Get-Date).AddSeconds(60);$version=$null
do {
    try { $version=Invoke-RestMethod -Uri ('http://'+$HostAddress+'/api/version') -TimeoutSec 2 } catch { Start-Sleep -Seconds 1 }
} while (!$version -and (Get-Date) -lt $deadline)
if (!$version) { throw 'Isolated Ollama service did not become ready' }
& $exe pull $Model
if ($LASTEXITCODE -ne 0) { throw 'Ollama public test model pull failed' }
$tags=Invoke-RestMethod -Uri ('http://'+$HostAddress+'/api/tags')
$selected=@($tags.models | Where-Object name -eq $Model)
if (!$selected.Count -or !$selected[0].digest) { throw 'Pulled model identity is absent' }
Write-Json $ReportPath @{version=$version.version;model=$selected[0];server_pid=$server.Id;url=('http://'+$HostAddress);installer_sha256=$ollamaInput.sha256;model_source=('https://ollama.com/library/'+$Model.Split(':')[0]);model_directory=$env:OLLAMA_MODELS}
