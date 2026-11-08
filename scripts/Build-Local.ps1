param([switch]$Background, [switch]$Status, [switch]$Domestic, [string]$Ref = 'HEAD')
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$common = & git -C $repo rev-parse --path-format=absolute --git-common-dir
if ($LASTEXITCODE -ne 0) { throw 'Cannot locate Git state' }
$state = Join-Path $common 'local-build'
$config = Get-Content -LiteralPath (Join-Path $state 'config.json') -Raw | ConvertFrom-Json
$driver = Join-Path $PSScriptRoot 'local_build.py'
if ($Status) {
    & $config.python -X utf8 $driver status --repo $repo
    exit $LASTEXITCODE
}
$sha = & git -C $repo rev-parse --verify --end-of-options "$Ref`^{commit}"
if ($LASTEXITCODE -ne 0 -or $sha -notmatch '^[0-9a-f]{40,64}$') { throw 'Invalid commit reference' }
$profileArguments = @()
if ($Domestic) { $profileArguments += '--domestic' } else { $profileArguments += '--cached' }
if ($Background) {
    Start-Process -FilePath $config.python -WindowStyle Hidden -WorkingDirectory $repo -ArgumentList (@(
        '-X', 'utf8', ('"' + $driver + '"'), 'build', '--repo', ('"' + $repo + '"'), '--ref', $sha
    ) + $profileArguments) | Out-Null
    Write-Output "Local build queued: $sha. Status: scripts/Build-Local.ps1 -Status"
} else {
    & $config.python -X utf8 $driver build --repo $repo --ref $sha @profileArguments
    exit $LASTEXITCODE
}
