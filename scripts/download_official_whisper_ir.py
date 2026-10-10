"""Download the Intel-published Whisper IR needed for the static NPU pipeline."""

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=['base.en', 'base', 'small'], default='base.en')
    args = parser.parse_args()
    snapshot_download(
        f"OpenVINO/whisper-{args.model}-fp16-ov",
        local_dir=Path(f"OpenVINO-whisper-{args.model.replace('.', '-')}-fp16-ov"),
    )
