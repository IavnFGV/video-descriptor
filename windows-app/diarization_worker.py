"""Offline native pyannote worker; accepts PCM WAV, never invokes speech recognition."""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import time
import wave
from pathlib import Path


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    for attempt in range(20):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 19:
                raise PermissionError('Не удалось сохранить диаризацию: файл результатов остаётся занят. Повторите операцию.') from None
            time.sleep(.05)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--device', choices=['cpu', 'xpu'], required=True)
    parser.add_argument('--audio', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--progress', type=Path)
    parser.add_argument('--doctor', action='store_true')
    args = parser.parse_args()
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYANNOTE_METRICS_ENABLED='0')
    import torch
    from pyannote.audio import Pipeline
    if not (args.model / 'config.yaml').is_file():
        raise ValueError('Не найдена локальная модель диаризации. Укажите папку pyannote community-1.')
    if args.device == 'xpu':
        if not torch.xpu.is_available():
            raise RuntimeError('Intel GPU недоступен в окружении диаризации. Выберите CPU или подготовьте PyTorch XPU.')
        assert float((torch.arange(16, device='xpu', dtype=torch.float32) ** 2).sum().cpu()) == 1240
        torch.xpu.synchronize()
    if args.doctor:
        print(json.dumps({'ready': True, 'device': args.device, 'torch': torch.__version__,
                          'device_name': torch.xpu.get_device_name(0) if args.device == 'xpu' else 'CPU'}), flush=True)
        return
    if not args.audio or not args.output or not args.progress:
        parser.error('--audio, --output and --progress are required')
    import numpy as np
    torch.set_num_threads(4)

    def progress(message):
        save(args.progress, {'message': message})
        print(message, flush=True)

    progress(f'Говорящие · {args.device.upper()} · загружаем локальную модель; скачивания нет')
    pipeline = Pipeline.from_pretrained(str(args.model))
    pipeline.to(torch.device(args.device))
    with wave.open(str(args.audio), 'rb') as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
            raise ValueError('Диаризации нужен mono PCM16 WAV 16000 Гц.')
        raw = audio.readframes(audio.getnframes())
    signal = torch.from_numpy(np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768).unsqueeze(0)
    stages = {'segmentation': 'ищем смены голосов', 'embeddings': 'сравниваем голоса',
              'discrete_diarization': 'размечаем говорящих', 'clustering': 'объединяем одинаковые голоса'}
    last = {}

    def hook(step_name, step_artifact, file=None, total=None, completed=None):
        percent = min(100, int(100 * completed / total)) if total and completed is not None else None
        if last.get(step_name, -1) != percent:
            last[step_name] = percent
            progress(f'Говорящие · {args.device.upper()} · {stages.get(step_name, "обработка голосов")}' +
                     (f' · {percent}%' if percent is not None else ''))

    if args.device == 'xpu':
        torch.xpu.synchronize()
    started = time.monotonic()
    prediction = pipeline({'waveform': signal, 'sample_rate': 16000}, hook=hook)
    if args.device == 'xpu':
        torch.xpu.synchronize()
    duration = len(raw) / 32000
    turns = [{'start': float(segment.start), 'end': float(segment.end), 'speaker': str(speaker)}
             for segment, speaker in prediction.exclusive_speaker_diarization]
    if any(not math.isfinite(row['start']) or not math.isfinite(row['end']) or
           not 0 <= row['start'] <= row['end'] <= duration + .1 for row in turns):
        raise ValueError('Диаризация вернула неверные границы голосов. Исходная расшифровка сохранена.')
    save(args.output, {'turns': turns, 'device': args.device, 'torch': torch.__version__,
                       'device_name': torch.xpu.get_device_name(0) if args.device == 'xpu' else 'CPU',
                       'python': __import__('sys').version.split()[0], 'pyannote': importlib.metadata.version('pyannote.audio'),
                       'duration': duration, 'pcm_sha256': hashlib.sha256(raw).hexdigest(),
                       'audio_sha256': hashlib.sha256(args.audio.read_bytes()).hexdigest(),
                       'inference_seconds': time.monotonic() - started})
    progress('Голоса определены; сохраняем отдельную версию')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — worker boundary returns a readable failure to the UI.
        import sys
        # Machine-readable failure for the parent; no tokens or transcript in the log.
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
        raise SystemExit(1) from None
