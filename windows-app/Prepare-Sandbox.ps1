param([switch]$Enable, [switch]$Launch)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$runId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$runDirectory = Join-Path $PSScriptRoot ('runtime\sandbox\' + $runId)
$inputDirectory = Join-Path $runDirectory 'input'
$reportDirectory = Join-Path $runDirectory 'reports'
New-Item -ItemType Directory -Force -Path $inputDirectory,$reportDirectory | Out-Null
$artifacts = Get-Content -LiteralPath (Join-Path $projectDirectory 'dist\SHA256SUMS.json') -Raw | ConvertFrom-Json
foreach ($artifact in $artifacts) {
    $source = Join-Path $projectDirectory ('dist\' + $artifact.file)
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $artifact.sha256) { throw ('Checksum mismatch: ' + $artifact.file) }
    Copy-Item -LiteralPath $source -Destination (Join-Path $inputDirectory $artifact.file)
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'verify_release.py') -Destination $inputDirectory
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'sandbox\Run-GuestChecks.ps1') -Destination $inputDirectory
$zip = @($artifacts | Where-Object { $_.file -like '*.zip' })
$installer = @($artifacts | Where-Object { $_.file -like '*-setup.exe' })
if ($zip.Count -ne 1 -or $installer.Count -ne 1) { throw 'Expected exactly one ZIP and installer' }
# Windows PowerShell 5.1 can serialize a ConvertFrom-Json root array as {value,Count}.
$artifactManifest = @()
foreach ($artifact in $artifacts) { $artifactManifest += @{file=[string]$artifact.file; bytes=[long]$artifact.bytes; sha256=[string]$artifact.sha256} }
@{zip=[string]$zip[0].file; installer=[string]$installer[0].file; artifacts=$artifactManifest} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $inputDirectory 'inputs.json') -Encoding UTF8
$escapedInput = [Security.SecurityElement]::Escape($inputDirectory)
$escapedReports = [Security.SecurityElement]::Escape($reportDirectory)
$configuration = @"
<Configuration>
  <MemoryInMB>4096</MemoryInMB>
  <Networking>Disable</Networking>
  <vGPU>Disable</vGPU>
  <AudioInput>Disable</AudioInput>
  <VideoInput>Disable</VideoInput>
  <PrinterRedirection>Disable</PrinterRedirection>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <MappedFolders>
    <MappedFolder><HostFolder>$escapedInput</HostFolder><SandboxFolder>C:\VD-Input</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$escapedReports</HostFolder><SandboxFolder>C:\VD-Reports</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
  </MappedFolders>
  <LogonCommand><Command>powershell.exe -NoProfile -NoExit -ExecutionPolicy Bypass -File C:\VD-Input\Run-GuestChecks.ps1</Command></LogonCommand>
</Configuration>
"@
$configurationPath = Join-Path $runDirectory 'Video Descriptor.wsb'
$configuration | Set-Content -LiteralPath $configurationPath -Encoding UTF8
Write-Output ('Configuration: ' + $configurationPath)
Write-Output ('Reports: ' + $reportDirectory)
if ($Enable) {
    $statusFile = Join-Path $runDirectory 'feature-status.json'
    $enableScript = Join-Path $PSScriptRoot 'sandbox\Enable-Sandbox.ps1'
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $enableScript + '" -StatusFile "' + $statusFile + '"'
    $adminProcess = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -ArgumentList $arguments -Verb RunAs -WindowStyle Hidden -PassThru
    Write-Output ('Windows elevation requested; helper PID: ' + $adminProcess.Id)
    Write-Output ('Enable status will be saved to: ' + $statusFile)
}
if ($Launch) {
    $sandboxExe = Join-Path $env:SystemRoot 'System32\WindowsSandbox.exe'
    if (-not (Test-Path -LiteralPath $sandboxExe)) { throw 'Windows Sandbox is not available yet. Enable it and restart Windows if required, then open the prepared .wsb file.' }
    Start-Process -FilePath $sandboxExe -ArgumentList ('"' + $configurationPath + '"')
}
