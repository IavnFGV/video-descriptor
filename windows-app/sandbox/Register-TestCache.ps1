param(
    [Parameter(Mandatory)][string]$SourcePath,
    [Parameter(Mandatory)][ValidatePattern('^[a-z0-9-]+$')][string]$Component,
    [Parameter(Mandatory)][string]$Version,
    [Parameter(Mandatory)][uri]$Source,
    [string]$CacheDirectory
)
. "$PSScriptRoot\Acceptance.Common.ps1"
if (!$CacheDirectory) { $CacheDirectory=Join-Path $PSScriptRoot '..\runtime\acceptance-cache-v2' }
if ($Source.Scheme -ne 'https') { throw 'Provenance must identify an HTTPS upstream source' }
$item = Get-Item -LiteralPath $SourcePath
Assert-PlainTree $item.FullName
if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Links cannot be registered' }
$files = if ($item.PSIsContainer) { @(Get-ChildItem -LiteralPath $item.FullName -Recurse -File) } else { @($item) }
if (!$files.Count) { throw 'Empty cache object' }
$base = if ($item.PSIsContainer) { $item.FullName } else { $item.DirectoryName }
$entries = @($files | Sort-Object FullName | ForEach-Object {
    if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Links cannot be registered' }
    @{file=$_.FullName.Substring($base.Length+1); bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
})
$objectId = $Component + '-' + (Get-TextHash ('payload-v2:'+($entries | ConvertTo-Json -Depth 5 -Compress))).Substring(0,24)
$objectRoot = Join-Path $CacheDirectory $objectId
if (Test-Path -LiteralPath $objectRoot) { throw "Object exists: $objectRoot" }
New-Item -ItemType Directory -Path $objectRoot -Force | Out-Null
$payloadRoot=Join-Path $objectRoot 'payload'
New-Item -ItemType Directory -Path $payloadRoot -Force | Out-Null
foreach ($entry in $entries) {
    $dest = Get-ContainedPath $payloadRoot $entry.file
    New-Item -ItemType Directory -Path (Split-Path $dest) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $base $entry.file) -Destination $dest
}
Test-ObjectFiles $payloadRoot $entries
Write-Json (Join-Path $objectRoot 'cache-object.json') @{
    schema=1; id=$objectId; component=$Component; version=$Version; source=$Source.AbsoluteUri;payload='payload'
    acquired_at=(Get-Date).ToUniversalTime().ToString('o'); files=$entries; bytes=($files | Measure-Object Length -Sum).Sum
}
Write-Output $objectRoot
