# Idempotent guest-logon/host-CLI fallback after the single authorized reboot.
$ErrorActionPreference='Stop'
. "$PSScriptRoot\Acceptance.Common.ps1"
$machine=Get-CimInstance Win32_ComputerSystem
if ($env:USERNAME -ne 'WDAGUtilityAccount' -or $machine.Model -ne 'Virtual Machine' -or !(Get-Service CExecSvc -ErrorAction SilentlyContinue)) { throw 'REFUSED: not Windows Sandbox' }
if (!(Test-Path 'C:\VD-Results\checkpoint.json')) { return }
$checkpoint=Read-Json 'C:\VD-Results\checkpoint.json'
if ($checkpoint.state -ne 'RESTART_PENDING') { return }
$report=Read-Json 'C:\VD-Results\report.json'
$boot=(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
if ($boot -eq $report.restart.before_boot) { return }
& "$PSScriptRoot\Bootstrap-Acceptance.ps1"
