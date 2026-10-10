# Run in the existing Windows benchmark folder with .venv-npu.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$WorkerPython = Join-Path $PSScriptRoot '.venv-npu\Scripts\python.exe'
if (-not (Test-Path $WorkerPython)) { throw 'Run this in windows-benchmark with the existing .venv-npu' }
function Invoke-CheckedPython {
    param([string[]]$PythonArgs)
    & $WorkerPython @PythonArgs
    if ($LASTEXITCODE -ne 0) { throw "Python failed (exit $LASTEXITCODE). Results and error saved in JSON." }
}
Invoke-CheckedPython @('download_official_whisper_ir.py', '--model', 'small')
Invoke-CheckedPython @('benchmark_whisper.py', 'sample-frigg-900.wav', '--backend', 'openvino', '--device', 'NPU', '--model', 'OpenVINO-whisper-small-fp16-ov', '--language', 'auto', '--repeats', '2', '--output', 'whisper-small-npu-frigg.json')
Write-Host 'Benchmark complete. Text, timing, timestamps and sanity checks: whisper-small-npu-frigg.json'
Write-Host 'Starting multilingual worker on port 8766 (English worker on 8765 is independent).'
try {
    $Health = Invoke-RestMethod 'http://localhost:8766/health' -TimeoutSec 2
    if ($Health.model -ne 'small' -or -not $Health.multilingual -or $Health.device -ne 'NPU') {
        throw 'Port 8766 is used by another service'
    }
    Write-Host 'Multilingual worker is already running'; exit 0
} catch {
    if ($_.Exception.Message -eq 'Port 8766 is used by another service') { throw }
}
$Worker = Start-Process -FilePath $WorkerPython -ArgumentList @('-u', 'whisper_npu_server.py', '--model', 'OpenVINO-whisper-small-fp16-ov', '--model-name', 'small', '--port', '8766') -WorkingDirectory $PSScriptRoot -RedirectStandardOutput (Join-Path $PSScriptRoot 'whisper-small-worker.log') -RedirectStandardError (Join-Path $PSScriptRoot 'whisper-small-worker.err.log') -WindowStyle Hidden -PassThru
$Worker.Id | Set-Content 'whisper-small-worker.pid'
Write-Host "Worker PID=$($Worker.Id); check http://localhost:8766/health and whisper-small-worker.log"
