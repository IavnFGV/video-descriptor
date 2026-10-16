"""Windows NPU worker: run with the existing OpenVINO benchmark environment."""

import argparse
import hashlib
import io
import json
import math
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def read_audio(body):
    import numpy as np

    with wave.open(io.BytesIO(body), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
            raise ValueError("Expected mono PCM16 WAV at 16000 Hz")
        frames = stream.getnframes()
        if not 0 < frames <= 300 * 16000:
            raise ValueError("Send between 0 and 300 seconds of audio per request")
        raw = stream.readframes(frames)
        if len(raw) != frames * 2:
            raise ValueError("Truncated WAV")
    return (np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0).tolist(), frames / 16000


def model_digest(folder):
    digest = hashlib.sha256()
    files = sorted(p for p in folder.iterdir() if p.suffix in {".xml", ".bin", ".json"})
    for path in files:
        digest.update(path.name.encode())
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
    return digest.hexdigest()


def make_handler(pipeline, info):
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def respond(self, code, value):
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self.respond(200, info)
            else:
                self.respond(404, {"error": "Unknown endpoint"})

        def do_POST(self):
            if self.path != "/transcribe":
                return self.respond(404, {"error": "Unknown endpoint"})
            try:
                if self.headers.get("X-Whisper-Model") != info["model"]:
                    raise ValueError(f"This worker serves {info['model']} only")
                language = self.headers.get("X-Language", "auto")
                if not info.get('multilingual') and language not in {"en", "auto"}:
                    raise ValueError("base.en supports English audio only")
                if language != 'auto' and (not language.isalpha() or len(language) not in {2, 3}):
                    raise ValueError('Invalid language code')
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 10 * 1024 * 1024:
                    raise ValueError("Invalid WAV request length")
                self.connection.settimeout(60)
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("Incomplete request")
                audio, duration = read_audio(body)
            except (ValueError, OSError, EOFError, wave.Error) as exc:
                return self.respond(400, {"error": str(exc)})
            try:
                with lock:
                    started = time.perf_counter()
                    print(f"{info['device']}: processing {duration:.1f}s of audio", flush=True)
                    options = {}
                    if info.get('multilingual'):
                        options['task'] = 'transcribe'
                        if language != 'auto':
                            options['language'] = f'<|{language}|>'
                    result = pipeline.generate(audio, num_beams=1, return_timestamps=True, **options)
                    chunks = result.chunks or []
                    if chunks and isinstance(chunks[0], (list, tuple)):
                        chunks = chunks[0]
                    segments = []
                    for chunk in chunks:
                        begin, end = float(chunk.start_ts), float(chunk.end_ts)
                        if not (math.isfinite(begin) and math.isfinite(end)
                                and 0 <= begin <= end <= duration + 1):
                            raise ValueError(f"{info['device']} returned invalid timestamps")
                        if chunk.text.strip() and begin < duration:
                            segments.append({"start": begin, "end": min(end, duration),
                                             "text": chunk.text.strip()})
                    elapsed = time.perf_counter() - started
                    print(f"{info['device']}: done in {elapsed:.2f}s, segments={len(segments)}", flush=True)
                self.respond(200, {"segments": segments, "audio_seconds": duration,
                                   "seconds": elapsed, "engine": info})
            except Exception as exc:  # noqa: BLE001 — API boundary preserves diagnostics.
                self.respond(500, {"error": str(exc)})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("OpenVINO-whisper-base-en-fp16-ov"))
    parser.add_argument("--model-name", choices=['base.en', 'base', 'small'], default='base.en')
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    import openvino as ov
    import openvino_genai as genai

    if "NPU" not in ov.Core().available_devices:
        raise RuntimeError("NPU unavailable: check Windows Intel NPU driver")
    config = json.loads((args.model / "config.json").read_text(encoding="utf-8"))
    expected = 51864 if args.model_name == 'base.en' else 51865
    if config.get("vocab_size") != expected:
        raise ValueError("Model vocabulary does not match --model-name")
    expected_layers = 12 if args.model_name == 'small' else 6
    if config.get('encoder_layers') != expected_layers:
        raise ValueError('Model size does not match --model-name')
    print("Loading FP16 Whisper on NPU (STATIC_PIPELINE=True)...", flush=True)
    pipeline = genai.WhisperPipeline(str(args.model), "NPU", STATIC_PIPELINE=True)
    info = {"protocol": 1, "device": "NPU", "model": args.model_name, "pipeline": "static",
            "multilingual": args.model_name != 'base.en',
            "num_beams": 1, "model_sha256": model_digest(args.model),
            "openvino": ov.__version__, "genai": genai.__version__}
    with ThreadingHTTPServer((args.bind, args.port), make_handler(pipeline, info)) as server:
        print(f"READY: port={args.port}; GET /health; POST /transcribe", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Stopped", flush=True)


if __name__ == "__main__":
    main()
