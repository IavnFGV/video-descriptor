$ErrorActionPreference = 'Stop'
$StageOrder = @('preflight','installer','desktop','whisper','ollama-install','ollama-model','ollama-inference','translation','notes','cleanup')
$StageDependencies = @{
    preflight=@(); installer=@('preflight'); desktop=@('installer'); whisper=@('desktop')
    'ollama-install'=@('desktop'); 'ollama-model'=@('ollama-install'); 'ollama-inference'=@('ollama-model')
    translation=@('whisper','ollama-inference'); notes=@('translation'); cleanup=@('preflight')
}
function Write-Json($Path, $Value) {
    # Same-directory rename prevents a reader from accepting half a report.
    $temp = $Path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    $Value | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $Path -Force
}
function Read-Json($Path) {
    for ($attempt=0; $attempt -lt 20; $attempt++) {
        $stream=$null; $reader=$null
        try {
            $sharing=[IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
            $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,$sharing)
            $reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true)
            $value=$reader.ReadToEnd() | ConvertFrom-Json
            break
        } catch {
            if ($attempt -eq 19) { throw }
            Start-Sleep -Milliseconds 50
        } finally { if ($reader) { $reader.Dispose() } elseif ($stream) { $stream.Dispose() } }
    }
    # PowerShell 5.1 emits a JSON root array as a single pipeline object.
    if ($value -is [array]) { foreach ($entry in $value) { Write-Output $entry } } else { Write-Output $value }
}
function ConvertTo-CanonicalJson($Value) {
    function Normalize($Item) {
        if ($null -eq $Item) { return $null }
        if ($Item -is [System.Collections.IDictionary]) {
            $result=[ordered]@{}
            foreach ($key in @($Item.Keys | Sort-Object)) { $result[$key]=Normalize $Item[$key] }
            return $result
        }
        if ($Item -is [pscustomobject]) {
            $result=[ordered]@{}
            foreach ($property in @($Item.PSObject.Properties | Sort-Object Name)) { $result[$property.Name]=Normalize $property.Value }
            return $result
        }
        if ($Item -is [System.Collections.IEnumerable] -and $Item -isnot [string]) {
            $result=@(foreach ($entry in $Item) { Normalize $entry })
            return ,$result
        }
        return $Item
    }
    Normalize $Value | ConvertTo-Json -Depth 40 -Compress
}
function Get-TextHash([string]$Value) {
    $hash = [Security.Cryptography.SHA256]::Create()
    try { ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)))).Replace('-','').ToLowerInvariant() }
    finally { $hash.Dispose() }
}
function Get-StageClosure($Requested) {
    $selected = @{}
    function Add-Stage($Name) {
        if ($selected.ContainsKey($Name)) { return }
        foreach ($dependency in $StageDependencies[$Name]) { Add-Stage $dependency }
        $selected[$Name] = $true
    }
    foreach ($name in $Requested) { Add-Stage $name }
    @($StageOrder | Where-Object { $selected.ContainsKey($_) })
}
function Get-ContainedPath([string]$Root, [string]$Relative) {
    if ([IO.Path]::IsPathRooted($Relative)) { throw "Absolute member: $Relative" }
    $prefix = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $target = [IO.Path]::GetFullPath((Join-Path $Root $Relative))
    if (-not $target.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Path escapes root: $Relative" }
    $target
}
function Assert-PlainTree([string]$Path) {
    $item=Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point: $Path" }
    if ($item.PSIsContainer) {
        foreach ($child in Get-ChildItem -LiteralPath $item.FullName -Force) { Assert-PlainTree $child.FullName }
    }
}
function Test-ObjectFiles($Root, $Files) {
    foreach ($entry in $Files) {
        $path = Get-ContainedPath $Root $entry.file
        $item = Get-Item -LiteralPath $path
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point: $path" }
        $parent=$item.Directory
        while ($parent -and $parent.FullName.Length -ge ([IO.Path]::GetFullPath($Root)).TrimEnd('\').Length) {
            if ($parent.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse directory: $($parent.FullName)" }
            $parent=$parent.Parent
        }
        if ($item.Length -ne $entry.bytes -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
            throw "Integrity mismatch: $path"
        }
    }
}
function Get-CachePayload($Object) {
    $root=Get-ContainedPath 'C:\VD-Cache' $Object.id
    if ($Object.payload) { return Get-ContainedPath $root $Object.payload }
    return $root
}
