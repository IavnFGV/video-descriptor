param(
    [ValidateSet('Detect', 'Install', 'Verify')][string]$Mode = 'Detect',
    [Parameter(Mandatory=$true)][string]$LoaderPath,
    [string]$InstallerPath,
    [string]$RuntimeDirectory,
    [string]$ExpectedSha256,
    [string]$RuntimeVersion,
    [Parameter(Mandatory=$true)][string]$LogPath
)
$ErrorActionPreference = 'Stop'
# Setup may inherit PSModulePath from PowerShell 7; use this process's Windows modules.
$env:PSModulePath = (Join-Path $PSHOME 'Modules') + ';' + $env:PSModulePath

function Write-Result($event, $details) {
    @{timestamp=(Get-Date).ToString('o'); event=$event; details=$details} |
        ConvertTo-Json -Compress -Depth 5 | Add-Content -LiteralPath $LogPath -Encoding UTF8
}

function Get-RuntimeVersion([string]$Folder) {
    $pointer = [IntPtr]::Zero
    try {
        $folderArgument = if ($Folder) { $Folder } else { $null }
        $result = [VideoDescriptor.WebViewPrerequisite]::GetAvailableCoreWebView2BrowserVersionString($folderArgument, [ref]$pointer)
        if ($result -ne 0 -or $pointer -eq [IntPtr]::Zero) { return $null }
        $version = [Runtime.InteropServices.Marshal]::PtrToStringUni($pointer)
        if ($Folder) {
            if (Test-Path -LiteralPath (Join-Path $Folder 'msedgewebview2.exe')) { return $version }
            return $null
        }
        # A stale registry entry can survive a broken Evergreen update in Sandbox.
        $roots = @("${env:ProgramFiles(x86)}\Microsoft\EdgeWebView\Application",
                   "$env:LOCALAPPDATA\Microsoft\EdgeWebView\Application")
        foreach ($root in $roots) {
            if (Test-Path -LiteralPath (Join-Path $root "$version\msedgewebview2.exe")) { return $version }
        }
        return $null
    } finally {
        if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::FreeCoTaskMem($pointer) }
    }
}

try {
    if ($RuntimeDirectory) { $RuntimeDirectory = [IO.Path]::GetFullPath($RuntimeDirectory) }
    $loader = [IO.Path]::GetFullPath($LoaderPath).Replace('"', '""')
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace VideoDescriptor {
    public static class WebViewPrerequisite {
        [DllImport(@"$loader", CharSet=CharSet.Unicode, CallingConvention=CallingConvention.StdCall)]
        public static extern int GetAvailableCoreWebView2BrowserVersionString(string folder, out IntPtr version);
    }
}
"@
    if ($Mode -ne 'Verify') {
        $version = $null
        $localRuntimePresent = $RuntimeDirectory -and (Test-Path -LiteralPath $RuntimeDirectory)
        if ($localRuntimePresent) {
            $version = Get-RuntimeVersion $RuntimeDirectory
            if ($RuntimeVersion -and $version -ne $RuntimeVersion) { $version = $null }
        }
        if (-not $localRuntimePresent) { $version = Get-RuntimeVersion }
        Write-Result 'detect' @{version=$version; available=[bool]$version}
        if ($version) { exit 0 }
        if ($Mode -eq 'Detect') { exit 20 }
    }
    if (-not $InstallerPath -or -not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
        throw 'The downloaded WebView2 installer is missing.'
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $InstallerPath
    $publisher = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { '' }
    $hash = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Result 'installer_verification' @{sha256=$hash; status=[string]$signature.Status; publisher=$publisher}
    if ($ExpectedSha256 -and $hash -ne $ExpectedSha256) { throw 'WebView2 package checksum does not match the release.' }
    if ($signature.Status -ne 'Valid' -or $publisher -notmatch '(^|,\s*)CN=Microsoft Corporation(,|$)' -or
        $publisher -notmatch '(^|,\s*)O=Microsoft Corporation(,|$)') {
        throw 'WebView2 installer signature is not a valid Microsoft Corporation signature. It was not executed.'
    }
    if ($Mode -eq 'Verify') { exit 0 }
    if (-not $ExpectedSha256 -or $hash -ne $ExpectedSha256 -or
        -not $RuntimeDirectory -or -not $RuntimeVersion) {
        throw 'Fixed WebView2 package checksum or installation parameters do not match the release.'
    }
    # Official Fixed Version distribution: no system installer, registry or ACL changes.
    $staging = Join-Path $env:TEMP ('VD-WebView2-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $staging | Out-Null
    & "$env:SystemRoot\System32\expand.exe" '-F:*' $InstallerPath $staging | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not extract the verified WebView2 package.' }
    $source = Join-Path $staging "Microsoft.WebView2.FixedVersionRuntime.$RuntimeVersion.x64"
    $version = Get-RuntimeVersion $source
    if ($version -ne $RuntimeVersion) { throw 'Extracted WebView2 Runtime version does not match the release.' }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $RuntimeDirectory) | Out-Null
    if (Test-Path -LiteralPath $RuntimeDirectory) {
        $preserved = $RuntimeDirectory + '.incomplete-' + [guid]::NewGuid().ToString('N')
        Move-Item -LiteralPath $RuntimeDirectory -Destination $preserved
        Write-Result 'preserved_incomplete_runtime' @{path=$preserved}
    }
    Move-Item -LiteralPath $source -Destination $RuntimeDirectory
    $version = Get-RuntimeVersion $RuntimeDirectory
    if ($version -ne $RuntimeVersion) { throw 'WebView2 Runtime is unavailable after extraction.' }
    Write-Result 'ready' @{version=$version; distribution='fixed'; path=$RuntimeDirectory}
    exit 0
} catch {
    Write-Result 'error' @{message=$_.Exception.Message}
    exit 1
}
