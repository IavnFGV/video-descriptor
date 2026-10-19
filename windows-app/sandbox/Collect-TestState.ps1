$ErrorActionPreference='Stop'
$machine=Get-CimInstance Win32_ComputerSystem
if ($env:USERNAME -ne 'WDAGUtilityAccount' -or $machine.Model -ne 'Virtual Machine' -or !(Get-Service CExecSvc -ErrorAction SilentlyContinue)) { throw 'REFUSED: not disposable Sandbox' }
$state=@{
    timestamp=(Get-Date).ToUniversalTime().ToString('o')
    boot=(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
    sac=(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy').VerifiedAndReputablePolicyState
    processes=@(Get-CimInstance Win32_Process | Where-Object Name -in @('python.exe','powershell.exe','VideoDescriptor.exe','ollama.exe') | Select-Object Name,ProcessId,ParentProcessId,ExecutablePath,CommandLine)
    ci_runtime_ready=(Test-Path 'C:\VD-Work\ci-verifier-runtime\python\python.exe')
}
$state | ConvertTo-Json -Depth 8 | Set-Content C:\VD-Results\diagnostic-state.json -Encoding UTF8
