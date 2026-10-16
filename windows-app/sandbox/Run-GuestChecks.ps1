$ErrorActionPreference = 'Stop'
$inputDirectory = 'C:\VD-Input'
$reportDirectory = 'C:\VD-Reports'
$bootstrapDirectory = Join-Path $env:USERPROFILE 'VD-bootstrap'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
try {
    Write-Host 'Video Descriptor: checking ZIP and installer in Windows Sandbox. Network and vGPU are disabled.'
    $inputs = Get-Content -LiteralPath (Join-Path $inputDirectory 'inputs.json') -Raw | ConvertFrom-Json
    foreach ($artifact in $inputs.artifacts) {
        $path = Join-Path $inputDirectory $artifact.file
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $artifact.sha256) { throw ('Checksum mismatch: ' + $artifact.file) }
    }
    $zipPath = Join-Path $inputDirectory $inputs.zip
    Expand-Archive -LiteralPath $zipPath -DestinationPath $bootstrapDirectory
    $python = Join-Path $bootstrapDirectory 'python\python.exe'
    $arguments = '-X utf8 "' + (Join-Path $inputDirectory 'verify_release.py') + '" "' + $zipPath + '" --installer "' + (Join-Path $inputDirectory $inputs.installer) + '" --output "' + (Join-Path $reportDirectory 'verification-release.json') + '"'
    $testProcess = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $bootstrapDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $reportDirectory 'stdout.log') -RedirectStandardError (Join-Path $reportDirectory 'stderr.log')
    @{status='running'; environment='Windows Sandbox'; started_at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportDirectory 'status.json') -Encoding UTF8
    Write-Host 'Checks are running. Reports are saved to the dedicated host reports folder. Keep this window open.'
    $testProcess.WaitForExit()
    $testProcess.Refresh()
    if ($testProcess.ExitCode -ne 0) { throw ('Checks failed; exit ' + $testProcess.ExitCode + '. See stderr.log.') }
    $report = Get-Content -LiteralPath (Join-Path $reportDirectory 'verification-release.json') -Raw | ConvertFrom-Json
    $report | Add-Member -NotePropertyName execution_environment -NotePropertyValue 'Windows Sandbox; no network; vGPU disabled'
    $report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $reportDirectory 'verification-release.json') -Encoding UTF8
    @{status='passed'; environment='Windows Sandbox'; finished_at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportDirectory 'status.json') -Encoding UTF8
    Write-Host 'PASSED. ZIP and installer checks completed. Reports are already saved on the host.' -ForegroundColor Green
} catch {
    @{status='failed'; message=$_.Exception.Message; finished_at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportDirectory 'status.json') -Encoding UTF8
    Write-Host $_.Exception.Message -ForegroundColor Red
}
