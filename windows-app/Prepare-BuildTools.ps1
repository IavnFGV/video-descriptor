param([string]$CacheDirectory = (Join-Path $PSScriptRoot 'runtime\build-cache'))
$ErrorActionPreference = 'Stop'
$inputs = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'release-inputs.json') -Raw | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $CacheDirectory | Out-Null
$setupPath = Join-Path $CacheDirectory 'innosetup-6.7.3.exe'
$downloadArguments = @('--url', $inputs.inno.url, '--output', $setupPath, '--sha256', $inputs.inno.sha256)
if ($inputs.inno.api_url) { $downloadArguments += @('--fallback-url', $inputs.inno.api_url) }
& python -X utf8 (Join-Path $PSScriptRoot '..\scripts\download_build_file.py') @downloadArguments
if ($LASTEXITCODE -ne 0) { throw 'Could not download verified Inno Setup after retries' }
if ((Get-FileHash -LiteralPath $setupPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $inputs.inno.sha256) { throw 'Inno Setup checksum mismatch' }
$signature = Get-AuthenticodeSignature -LiteralPath $setupPath
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'CN=Pyrsys B\.V\.') { throw 'Inno Setup publisher signature mismatch' }
$compilerDirectory = Join-Path ([IO.Path]::GetFullPath($CacheDirectory)) 'inno-6.7.3'
$compiler = Join-Path $compilerDirectory 'ISCC.exe'
if (-not (Test-Path -LiteralPath $compiler)) {
    $process = Start-Process -FilePath ([IO.Path]::GetFullPath($setupPath)) -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/CURRENTUSER','/TASKS=""',('/DIR="' + $compilerDirectory + '"')) -WindowStyle Hidden -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw ('Build tool setup failed: ' + $process.ExitCode) }
}
Write-Output $compiler
