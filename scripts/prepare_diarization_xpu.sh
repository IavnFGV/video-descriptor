#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -c /dev/dxg ]]; then
    echo 'Нет /dev/dxg. Откройте профиль devcontainer Intel GPU (WSL2).'
    exit 1
fi
export LD_LIBRARY_PATH="/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
python -m venv --system-site-packages .venv-diarization-xpu
.venv-diarization-xpu/bin/python -m pip install --upgrade pip
.venv-diarization-xpu/bin/python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/xpu
.venv-diarization-xpu/bin/python -m pip install pyannote.audio
.venv-diarization-xpu/bin/python -m pip install -e .
.venv-diarization-xpu/bin/python -m pip check
.venv-diarization-xpu/bin/python scripts/probe_diarization_xpu.py
