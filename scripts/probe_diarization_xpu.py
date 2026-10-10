"""Check Intel XPU, optionally benchmark diarization of a PCM16 WAV excerpt."""
import argparse
import hashlib
import json
import os
import time
import wave
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path)
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--device', choices=['cpu', 'xpu'], default='xpu')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error('--seconds должен быть положительным')
    os.environ['PYANNOTE_METRICS_ENABLED'] = '0'
    import torch

    print(f'PyTorch {torch.__version__}; XPU available={torch.xpu.is_available()}', flush=True)
    if args.device == 'xpu':
        if not torch.xpu.is_available():
            raise SystemExit('Intel XPU недоступен; CPU автоматически не подставляем.')
        print(torch.xpu.get_device_name(0), flush=True)
        x = torch.arange(16, device='xpu', dtype=torch.float32)
        assert float((x * x).sum().cpu()) == 1240
        torch.xpu.synchronize()
        print('Расчёт на XPU выполнен.', flush=True)
    if not args.audio:
        return
    import numpy as np
    from pyannote.audio import Pipeline

    token = os.getenv('HF_TOKEN', '')
    env = Path('.env.huggingface')
    if not token and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith('HF_TOKEN='):
                token = line.partition('=')[2].strip().strip('\"\'')
    if not token:
        raise SystemExit('Нужен HF_TOKEN в .env.huggingface')
    with wave.open(str(args.audio)) as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise SystemExit('Нужен mono PCM16 WAV')
        rate = wav.getframerate()
        raw = wav.readframes(min(wav.getnframes(), args.seconds * rate))
    waveform = torch.from_numpy(np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768).unsqueeze(0)
    torch.set_num_threads(4)
    started = time.monotonic()
    pipeline = Pipeline.from_pretrained('pyannote/speaker-diarization-community-1', token=token)
    pipeline.to(torch.device(args.device))
    load_seconds = time.monotonic() - started

    def hook(step_name, step_artifact, total=None, completed=None, **kwargs):
        print(f'{step_name}: {completed}/{total}', flush=True)

    if args.device == 'xpu':
        torch.xpu.synchronize()
    started = time.monotonic()
    result = pipeline({'waveform': waveform, 'sample_rate': rate}, hook=hook)
    if args.device == 'xpu':
        torch.xpu.synchronize()
    record = {
        'device': args.device, 'torch_version': torch.__version__,
        'model': 'pyannote/speaker-diarization-community-1',
        'audio': str(args.audio), 'pcm_sha256': hashlib.sha256(raw).hexdigest(),
        'audio_seconds': len(raw) / (2 * rate), 'load_seconds': load_seconds,
        'inference_seconds': time.monotonic() - started,
        'exclusive_turns': [{'start': s.start, 'end': s.end, 'speaker': sp}
                            for s, sp in result.exclusive_speaker_diarization],
    }
    print(json.dumps(record, ensure_ascii=False, indent=2), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
