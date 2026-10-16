param([Parameter(Mandatory=$true)][string]$StatusFile)
$ErrorActionPreference = 'Stop'
$statusDirectory = Split-Path -Parent $StatusFile
New-Item -ItemType Directory -Path $statusDirectory -Force | Out-Null
try {
    @{status='enabling'; started_at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $StatusFile -Encoding UTF8
    $result = Enable-WindowsOptionalFeature -Online -FeatureName 'Containers-DisposableClientVM' -All -NoRestart -ErrorAction Stop
    @{status='enabled'; restart_needed=[bool]$result.RestartNeeded; checked_at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $StatusFile -Encoding UTF8
} catch {
    @{status='error'; message=$_.Exception.Message; checked_at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $StatusFile -Encoding UTF8
    exit 1
}
