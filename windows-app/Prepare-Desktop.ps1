$ErrorActionPreference = 'Stop'
# Application-local SDK libraries only. Does not install a WebView2 runtime.
$inputSpec = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'release-inputs.json') -Raw | ConvertFrom-Json).webview2
$expected = $inputSpec.sha256
$destination = Join-Path $PSScriptRoot 'runtime\desktop-sdk'
$archive = Join-Path $PSScriptRoot 'runtime\build-cache\webview2.nupkg'
New-Item -ItemType Directory -Path (Split-Path $archive),$destination -Force | Out-Null
if (-not (Test-Path -LiteralPath $archive)) {
    Invoke-WebRequest -UseBasicParsing -Uri $inputSpec.url -OutFile $archive
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected) { throw 'WebView2 SDK checksum mismatch' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($archive)
try {
    foreach ($name in @('lib/net462/Microsoft.Web.WebView2.Core.dll', 'lib/net462/Microsoft.Web.WebView2.WinForms.dll', 'runtimes/win-x64/native/WebView2Loader.dll', 'LICENSE.txt')) {
        $entry = $zip.GetEntry($name)
        if (-not $entry) { throw "Missing SDK file: $name" }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $destination ([IO.Path]::GetFileName($name))), $true)
    }
} finally { $zip.Dispose() }
Add-Type -AssemblyName System.Windows.Forms,System.Drawing,System.Web.Extensions,System.Net.Http
$core = Join-Path $destination 'Microsoft.Web.WebView2.Core.dll'
$forms = Join-Path $destination 'Microsoft.Web.WebView2.WinForms.dll'
Add-Type -Path $core,$forms
$compiled = Join-Path $destination (([guid]::NewGuid().ToString('N')) + '.exe')
Add-Type -Path (Join-Path $PSScriptRoot 'DesktopHost.cs') -OutputAssembly $compiled -OutputType WindowsApplication -ReferencedAssemblies @($core,$forms,'System.Windows.Forms','System.Drawing','System.Web.Extensions','System.Net.Http')
Move-Item -LiteralPath $compiled -Destination (Join-Path $destination 'VideoDescriptor.exe') -Force
$sourceHash = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'DesktopHost.cs') -Algorithm SHA256).Hash.ToLowerInvariant()
@{ source_sha256 = $sourceHash; sdk_sha256 = $expected } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $destination 'desktop-build.json') -Encoding ASCII
Write-Output $destination
