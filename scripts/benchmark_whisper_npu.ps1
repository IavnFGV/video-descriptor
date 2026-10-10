# Run from Windows PowerShell after extracting windows-benchmark.zip.
param([string]$PythonExe = "")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Executable (exit $LASTEXITCODE)" }
}

if (-not (Test-Path ".venv-npu\Scripts\python.exe")) {
    $Candidates = @()
    if ($PythonExe) {
        $Candidates += @{Exe = $PythonExe; Prefix = @()}
    } else {
        foreach ($Name in @("python", "python3")) {
            $Command = Get-Command $Name -ErrorAction SilentlyContinue
            if ($Command) { $Candidates += @{Exe = $Command.Source; Prefix = @()} }
        }
        $Launcher = Get-Command "py" -ErrorAction SilentlyContinue
        if ($Launcher) {
            $Candidates += @{Exe = $Launcher.Source; Prefix = @("-3.12")}
            $Candidates += @{Exe = $Launcher.Source; Prefix = @("-3.11")}
        }
        foreach ($Version in @("312", "311")) {
            $InstalledPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python$Version\python.exe"
            if (Test-Path $InstalledPython) {
                $Candidates += @{Exe = $InstalledPython; Prefix = @()}
            }
        }
    }
    $SelectedPython = $null
    foreach ($Candidate in $Candidates) {
        $ProbeArguments = @($Candidate.Prefix) + @("-c", "import sys; print('%d.%d' % sys.version_info[:2])")
        try {
            $VersionOutput = & $Candidate.Exe @ProbeArguments 2>$null
            if ($LASTEXITCODE -eq 0 -and "$VersionOutput" -match '^3\.(11|12)$') {
                $SelectedPython = $Candidate
                break
            }
        } catch { continue }
    }
    if (-not $SelectedPython) {
        throw 'Python 3.11/3.12 not found. Reopen PowerShell after installation or pass -PythonExe "C:\path\to\python.exe".'
    }
    Write-Host "Using Python: $($SelectedPython.Exe)"
    Invoke-Checked $SelectedPython.Exe (@($SelectedPython.Prefix) + @("-m", "venv", ".venv-npu"))
}
$BenchmarkPython = Join-Path $PSScriptRoot ".venv-npu\Scripts\python.exe"
$PackagesReady = $false
try {
    & $BenchmarkPython -c "import numpy, openvino, openvino_genai, huggingface_hub"
    $PackagesReady = $LASTEXITCODE -eq 0
} catch { $PackagesReady = $false }
if (-not $PackagesReady) {
    Invoke-Checked $BenchmarkPython @("-m", "pip", "install", "openvino==2026.4.1", "openvino-genai==2026.4.1.0", "numpy==2.4.6", "huggingface_hub==1.21.0")
}
Invoke-Checked $BenchmarkPython @("-c", "import openvino as ov; d=ov.Core().available_devices; print(d); assert 'NPU' in d, 'NPU unavailable: check Intel driver'")

if (-not (Test-Path "OpenVINO-whisper-base-en-fp16-ov\openvino_encoder_model.xml")) {
    Invoke-Checked $BenchmarkPython @("download_official_whisper_ir.py")
}
Invoke-Checked $BenchmarkPython @("-m", "pip", "freeze") | Set-Content -Encoding utf8 "versions.txt"
foreach ($BenchmarkDevice in @("CPU", "NPU")) {
    $ResultPath = "openvino-" + $BenchmarkDevice.ToLower() + "-official-fp16-b1.json"
    $PipelineMode = if ($BenchmarkDevice -eq "NPU") { "static" } else { "dynamic" }
    Invoke-Checked $BenchmarkPython @("benchmark_whisper.py", "sample.wav", "--backend", "openvino", "--device", $BenchmarkDevice, "--openvino-pipeline", $PipelineMode, "--beams", "1", "--model", "OpenVINO-whisper-base-en-fp16-ov", "--output", $ResultPath)
}
$CpuResult = Get-Content -Raw "openvino-cpu-official-fp16-b1.json" | ConvertFrom-Json
$NpuResult = Get-Content -Raw "openvino-npu-official-fp16-b1.json" | ConvertFrom-Json
if ($CpuResult.audio_sha256 -ne $NpuResult.audio_sha256) { throw "Audio hashes differ" }
if (-not $CpuResult.sanity_checks_passed -or -not $NpuResult.sanity_checks_passed) {
    throw "Transcription checks failed; do not interpret timings as useful speedup"
}
Write-Host ("CPU: {0:N2}s; NPU: {1:N2}s; speedup: {2:N2}x" -f $CpuResult.warm_median_seconds, $NpuResult.warm_median_seconds, ($CpuResult.warm_median_seconds / $NpuResult.warm_median_seconds))
