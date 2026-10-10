"""Run on Windows: preserve raw Whisper chunks, including invalid timestamps."""
import argparse
import hashlib
import json
import math
import os
import time
import wave
from pathlib import Path


def main():
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='OpenVINO-whisper-small-fp16-ov')
    parser.add_argument('--output', type=Path, default=Path('npu-timestamps-debug.json'))
    parser.add_argument('audio', nargs='+', type=Path)
    args = parser.parse_args()
    import numpy as np
    import openvino_genai as genai

    report = {'model': args.model, 'device': 'NPU', 'genai': genai.__version__, 'runs': []}

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    started = time.monotonic()
    pipeline = genai.WhisperPipeline(args.model, 'NPU', STATIC_PIPELINE=True)
    report['load_seconds'] = time.monotonic() - started
    for audio in args.audio:
        with wave.open(str(audio)) as stream:
            assert (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) == (1, 2, 16000)
            raw = stream.readframes(stream.getnframes())
        seconds = len(raw) / 32000
        signal = (np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768).tolist()
        for repeat in range(2):
            run = {'file': str(audio), 'repeat': repeat + 1, 'audio_seconds': seconds,
                   'wav_sha256': hashlib.sha256(audio.read_bytes()).hexdigest()}
            started = time.monotonic()
            try:
                result = pipeline.generate(signal, task='transcribe', num_beams=1, return_timestamps=True)
                chunks = result.chunks or []
                if chunks and isinstance(chunks[0], (tuple, list)):
                    chunks = chunks[0]
                run['text'] = list(result.texts)
                run['chunks'] = []
                for index, chunk in enumerate(chunks):
                    start, end = float(chunk.start_ts), float(chunk.end_ts)
                    valid = (math.isfinite(start) and math.isfinite(end)
                             and 0 <= start <= end <= seconds + 1)
                    run['chunks'].append({'index': index, 'start': start, 'end': end,
                                          'text': chunk.text, 'valid_for_worker': valid})
            except (RuntimeError, ValueError, TypeError) as exc:
                run['error'] = str(exc)
            run['seconds'] = time.monotonic() - started
            report['runs'].append(run)
            save()
            print(f'{audio.name}: repeat={repeat + 1}, seconds={run["seconds"]:.2f}, '
                  f'invalid={sum(not c["valid_for_worker"] for c in run.get("chunks", []))}, '
                  f'error={run.get("error", "none")}', flush=True)


if __name__ == '__main__':
    main()
