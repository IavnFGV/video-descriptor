param([switch]$Apply, [int]$Keep = 3, [int]$Days = 7)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$common = & git -C $repo rev-parse --path-format=absolute --git-common-dir
if ($LASTEXITCODE -ne 0) { throw 'Cannot locate Git state' }
$config = Get-Content -LiteralPath (Join-Path $common 'local-build/config.json') -Raw | ConvertFrom-Json
$arguments = @('-X', 'utf8', (Join-Path $PSScriptRoot 'clean_local.py'), '--repo', $repo, '--keep', $Keep, '--days', $Days)
if ($Apply) { $arguments += '--apply' }
& $config.python @arguments
exit $LASTEXITCODE
