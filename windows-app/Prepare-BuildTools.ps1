param([string]$CacheDirectory = (Join-Path $PSScriptRoot 'runtime\build-cache'))
$ErrorActionPreference = 'Stop'
$inputs = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'release-inputs.json') -Raw | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $CacheDirectory | Out-Null
$setupPath = Join-Path $CacheDirectory 'innosetup-6.7.3.exe'
if (-not (Test-Path -LiteralPath $setupPath)) { Invoke-WebRequest -Uri $inputs.inno.url -OutFile $setupPath }
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
