param([switch]$Restart, [switch]$Stop, [switch]$Open)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$common = & git -C $repo rev-parse --path-format=absolute --git-common-dir
if ($LASTEXITCODE -ne 0) { throw 'Cannot locate Git state' }
$config = Get-Content -LiteralPath (Join-Path $common 'local-dev/config.json') -Raw | ConvertFrom-Json
$command = if ($Stop) { 'stop' } elseif ($Restart) { 'restart' } else { 'start' }
$arguments = @('-X', 'utf8', (Join-Path $PSScriptRoot 'run_dev.py'), '--repo', $repo, '--command', $command)
if ($Open) { $arguments += '--open' }
& $config.python @arguments
exit $LASTEXITCODE
