# Start the tested Windows worker in the background using the benchmark environment.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$WorkerPython = Join-Path $PSScriptRoot ".venv-npu\Scripts\python.exe"
if (-not (Test-Path $WorkerPython)) { throw "Use the existing Windows benchmark folder with .venv-npu" }
if (-not (Test-Path "OpenVINO-whisper-base-en-fp16-ov\config.json")) {
    throw "The tested official FP16 model must be in this folder"
}
$HealthUrl = "http://localhost:8765/health"
try {
    $Health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
    if ($Health.device -eq "NPU" -and $Health.model -eq "base.en" -and $Health.protocol -eq 1) {
        Write-Host "NPU worker is already running on port 8765"
        exit 0
    }
    throw "Port 8765 is used by an incompatible service"
} catch {
    if ($_.Exception.Message -eq "Port 8765 is used by an incompatible service") { throw }
}
$Worker = Start-Process -FilePath $WorkerPython -ArgumentList @("-u", "whisper_npu_server.py") -WorkingDirectory $PSScriptRoot -RedirectStandardOutput (Join-Path $PSScriptRoot "whisper-npu-worker.log") -RedirectStandardError (Join-Path $PSScriptRoot "whisper-npu-worker.err.log") -WindowStyle Hidden -PassThru
$Worker.Id | Set-Content "whisper-npu-worker.pid"
for ($Attempt = 0; $Attempt -lt 90; $Attempt++) {
    if ($Worker.HasExited) { throw "Worker exited; see whisper-npu-worker.err.log" }
    try {
        $Health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
        if ($Health.device -ne "NPU" -or $Health.model -ne "base.en" -or $Health.protocol -ne 1) {
            throw "Unexpected health response"
        }
        Write-Host "READY: NPU worker PID=$($Worker.Id), port=8765; runs in the background"
        exit 0
    } catch { }
    if ($Attempt % 5 -eq 0) { Write-Host "Loading NPU model... see whisper-npu-worker.log" }
    Start-Sleep -Seconds 1
}
throw "Worker startup timed out; inspect whisper-npu-worker.log and whisper-npu-worker.err.log"
