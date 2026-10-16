"""Read-only OpenVINO CPU/GPU adapter using the already installed Whisper IR."""
import argparse
import hashlib
import json
import sys
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from scripts.whisper_npu_server import make_handler, model_digest, read_audio
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--device', choices=['CPU', 'GPU', 'NPU'], default='CPU')
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--inventory', action='store_true')
    parser.add_argument('--probe', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    import openvino as ov
    import openvino_genai as genai
    core = ov.Core()
    available = core.available_devices
    inventory = {'devices': available, 'openvino': ov.__version__, 'genai': genai.__version__,
                 'model_present': (args.model / 'config.json').is_file()}
    if args.inventory:
        print(json.dumps(inventory), flush=True)
        return
    if not any(item.split('.')[0] == args.device for item in available):
        raise RuntimeError(f'{args.device} is not available in OpenVINO')
    config = json.loads((args.model / 'config.json').read_text(encoding='utf-8'))
    if config.get('encoder_layers') != 12 or config.get('vocab_size') != 51865:
        raise ValueError('Expected official multilingual Whisper small IR')
    started = time.monotonic()
    options = {'STATIC_PIPELINE': True} if args.device == 'NPU' else {}
    pipeline = genai.WhisperPipeline(str(args.model), args.device, **options)
    loading = time.monotonic() - started
    info = {'protocol': 1, 'device': args.device, 'model': 'small', 'pipeline': 'static' if args.device == 'NPU' else 'dynamic',
            'multilingual': True, 'word_timestamps': False, 'num_beams': 1,
            'model_sha256': model_digest(args.model), 'openvino': ov.__version__, 'genai': genai.__version__}
    if args.probe:
        audio, duration = read_audio(args.probe.read_bytes())
        started = time.monotonic()
        result = pipeline.generate(audio, task='transcribe', num_beams=1, return_timestamps=True)
        chunks = result.chunks or []
        if chunks and isinstance(chunks[0], (list, tuple)):
            chunks = chunks[0]
        rows = [{'start': float(c.start_ts), 'end': float(c.end_ts), 'text': c.text} for c in chunks]
        valid = all(0 <= row['start'] <= row['end'] <= duration + .1 for row in rows)
        report = {'engine': info, 'audio_seconds': duration, 'loading_seconds': loading,
                  'inference_seconds': time.monotonic() - started, 'segments': len(rows),
                  'valid_timestamps': valid,
                  'text_sha256': hashlib.sha256(str(result.texts).encode()).hexdigest()}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)
        if not rows or not valid:
            raise RuntimeError('Probe returned empty text or invalid timestamps')
        return
    with ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(pipeline, info)) as server:
        print(json.dumps({'ready': True, 'port': args.port, 'loading_seconds': loading, 'engine': info}), flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
