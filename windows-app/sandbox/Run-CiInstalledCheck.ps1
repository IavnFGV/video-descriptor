# Rehearse the exact CI installer/API check inside an already authorized disposable Sandbox.
param([ValidatePattern('^[a-z0-9-]+$')][string]$ReportName='ci-installed', [switch]$WithOllama)
$ErrorActionPreference='Stop'
. "$PSScriptRoot\Acceptance.Common.ps1"
$machine=Get-CimInstance Win32_ComputerSystem
if ($env:USERNAME -ne 'WDAGUtilityAccount' -or $machine.Model -ne 'Virtual Machine' -or !(Get-Service CExecSvc -ErrorAction SilentlyContinue)) { throw 'REFUSED: requires disposable Windows Sandbox' }
$reportDirectory=Get-ContainedPath 'C:\VD-Results' $ReportName
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
Start-Transcript -LiteralPath ($reportDirectory+'.bootstrap.log') -Force | Out-Null
try {
$plan=Read-Json 'C:\VD-Acceptance\plan.json'
$model=@($plan.cache | Where-Object component -eq 'whisper-model')
if ($model.Count -ne 1) { throw 'Expected one verified public Whisper fixture' }
$zip=@($plan.artifacts | Where-Object file -like '*.zip')[0].file
$installer=@($plan.artifacts | Where-Object file -like '*-setup.exe')[0].file
$tools='C:\VD-Work\ci-verifier-runtime'
if (!(Test-Path -LiteralPath (Join-Path $tools 'runtime-ready.txt'))) {
    # The outer installer driver needs only the embedded interpreter + stdlib.
    # Its real checks run with the NEW installed Python, not a second full ZIP tree.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive=[IO.Compression.ZipFile]::OpenRead((Join-Path 'C:\VD-Acceptance' $zip))
    try {
        foreach ($entry in $archive.Entries) {
            if (!$entry.FullName.StartsWith('python/') -or !$entry.Name) { continue }
            $target=Get-ContainedPath $tools $entry.FullName
            New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$target,$true)
        }
    } finally { $archive.Dispose() }
    'Minimal outer test driver runtime' | Set-Content (Join-Path $tools 'runtime-ready.txt')
}
# Only the completed harness installation in this disposable guest is replaced.
$registration=Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{CA05C8BE-4CF2-4BCA-9B3C-597742FF04D1}_is1' -ErrorAction SilentlyContinue
if ($registration.InstallLocation) {
    $prior=[IO.Path]::GetFullPath($registration.InstallLocation).TrimEnd('\')
    $testPrefix=[IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')+'\vd-installed-acceptance-'
    if ($prior.StartsWith($testPrefix,[StringComparison]::OrdinalIgnoreCase) -and (Test-Path (Join-Path $prior '.acceptance-installation.json'))) {
        Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prior+'\',[StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        $cleaned=Start-Process -FilePath (Join-Path $prior 'unins000.exe') -ArgumentList ('/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG='+$reportDirectory+'\previous-uninstall.log') -WindowStyle Hidden -PassThru
        $null=$cleaned.Handle
        if (!$cleaned.WaitForExit(180000)) { throw 'Prior test uninstaller timed out' }
        $cleaned.WaitForExit();$cleaned.Refresh()
        if ($cleaned.ExitCode -ne 0) { throw ('Failed prior marked test installation could not be removed; exit '+$cleaned.ExitCode) }
    }
}
$installed=Join-Path $env:LOCALAPPDATA 'Programs\VideoDescriptor'
Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($installed+'\',[StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
if (Test-Path -LiteralPath (Join-Path $installed 'unins000.exe')) {
    $uninstall=Start-Process -FilePath (Join-Path $installed 'unins000.exe') -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART' -PassThru -WindowStyle Hidden
    $null=$uninstall.Handle
    if (!$uninstall.WaitForExit(180000)) { throw 'Previous harness uninstaller timed out' }
    $uninstall.WaitForExit();$uninstall.Refresh()
    if ($uninstall.ExitCode -ne 0) { throw 'Previous test installation did not uninstall' }
}
$arguments='-X utf8 C:\VD-Acceptance\verify_installed.py --installer C:\VD-Acceptance\'+$installer+' --zip C:\VD-Acceptance\'+$zip+' --model "'+(Get-CachePayload $model[0])+'" --output '+$reportDirectory+'\report.json'
if ($WithOllama) { $arguments+=' --with-ollama --ollama-model '+$plan.ollama_model }
$process=Start-Process -FilePath (Join-Path $tools 'python\python.exe') -ArgumentList $arguments -PassThru -WindowStyle Hidden -RedirectStandardOutput ($reportDirectory+'.stdout.log') -RedirectStandardError ($reportDirectory+'.stderr.log')
$null=$process.Handle
if (!$process.WaitForExit(1800000)) { throw 'Installed API verifier timed out' }
$process.WaitForExit();$process.Refresh()
Write-Json ($reportDirectory+'-exit.json') @{exit_code=$process.ExitCode;timestamp=(Get-Date).ToUniversalTime().ToString('o')}
} catch { Write-Json ($reportDirectory+'-exit.json') @{exit_code=1;error=$_.Exception.Message} }
finally { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null }
