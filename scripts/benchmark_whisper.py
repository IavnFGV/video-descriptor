"""Measure the same PCM16/16 kHz audio with faster-whisper or OpenVINO."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import statistics
import time
import wave
from pathlib import Path


def inspect_transcription(text, segments, audio_seconds):
    """Catch broken output; passing these checks does not prove ASR accuracy."""
    problems = []
    if not text.strip():
        problems.append("empty transcription")
    for segment in segments:
        start, end = segment["start"], segment["end"]
        if start < -0.1 or end < start or end > audio_seconds + 1:
            problems.append("timestamps outside the audio or reversed")
            break
    words = re.findall(r"\w+", text.lower())
    if len(words) >= 20:
        counts = {}
        for word in words:
            counts[word] = counts.get(word, 0) + 1
        if max(counts.values()) / len(words) > .5:
            problems.append("more than half of the words repeat the same word")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--backend", choices=["faster-whisper", "openvino"], required=True)
    parser.add_argument("--device", choices=["CPU", "NPU"], default="CPU")
    parser.add_argument("--model", default="base.en",
                        help="faster-whisper name or exported OpenVINO folder")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--language", default="auto", help="auto, ru, uk, en, …")
    parser.add_argument("--start-seconds", type=float, default=0.0,
                        help="Start offset in the source WAV; useful for quality probes")
    parser.add_argument("--duration-seconds", type=float, default=None,
                        help="Limit the input duration after --start-seconds")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--beams", type=int, default=None,
                        help="Decoding beams: default 1 for OpenVINO, 5 for faster-whisper")
    parser.add_argument("--openvino-pipeline", choices=["static", "dynamic"], default="static",
                        help="OpenVINO WhisperPipeline mode; static is the official NPU path")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or args.threads < 1:
        parser.error("Use positive --repeats and --threads")
    if args.start_seconds < 0 or args.duration_seconds is not None and args.duration_seconds <= 0:
        parser.error("Offsets must be non-negative and duration must be positive")
    if args.backend == "faster-whisper" and args.device != "CPU":
        parser.error("faster-whisper has no NPU backend; use OpenVINO")
    beams = args.beams if args.beams is not None else (1 if args.backend == "openvino" else 5)
    if beams < 1:
        parser.error("--beams must be positive")
    if args.device == "NPU" and beams != 1:
        parser.error("Use --beams 1 for the static Whisper NPU pipeline")
    import numpy as np

    with wave.open(str(args.audio), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
            parser.error("Audio must be mono PCM16 WAV, 16000 Hz")
        source_seconds = stream.getnframes() / 16000
        audio = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2")
        audio = audio.astype(np.float32) / 32768.0
    first = round(args.start_seconds * 16000)
    last = len(audio) if args.duration_seconds is None else first + round(args.duration_seconds * 16000)
    audio = audio[first:last]
    audio_seconds = len(audio) / 16000
    if not audio_seconds:
        parser.error("Audio is empty")
    packages = ["numpy", "faster-whisper", "ctranslate2", "openvino", "openvino-genai"]
    versions = {}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    report = {
        "source_audio_sha256": hashlib.sha256(args.audio.read_bytes()).hexdigest(),
        "audio_sha256": hashlib.sha256(audio.tobytes()).hexdigest(),
        "audio_seconds": audio_seconds, "backend": args.backend, "device": args.device,
        "source_offset_seconds": first / 16000, "source_duration_seconds": source_seconds,
        "model": args.model, "platform": platform.platform(), "cpu_count": os.cpu_count(),
        "versions": versions, "runs": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        temporary = args.output.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(args.output)

    try:
        print(f"Loading {args.backend} / {args.device} / {args.model}", flush=True)
        if args.backend == "openvino":
            import openvino as ov
            import openvino_genai as genai

            devices = ov.Core().available_devices
            report["available_devices"] = devices
            if args.device not in devices:
                raise RuntimeError(f"{args.device} unavailable; detected: {devices}")
            started = time.perf_counter()
            # Do not substitute ASRPipeline here: WhisperPipeline with STATIC_PIPELINE is
            # the documented NPU implementation and has different state management.
            pipeline_options = ({"STATIC_PIPELINE": args.openvino_pipeline == "static"}
                                if args.device == "NPU" else {})
            model = genai.WhisperPipeline(args.model, args.device, **pipeline_options)
            multilingual = model.get_generation_config().is_multilingual
            options = {}
            if multilingual:
                options['task'] = 'transcribe'
                if args.language != 'auto':
                    options['language'] = f'<|{args.language}|>'
            elif args.language not in {'auto', 'en'}:
                raise ValueError('English-only model cannot recognize the selected language')
            report["load_seconds"] = time.perf_counter() - started
            report["settings"] = {"return_timestamps": True, "num_beams": beams,
                                  "task": "transcribe", "language": args.language, "vad": False,
                                  "pipeline": "WhisperPipeline",
                                  "STATIC_PIPELINE": pipeline_options.get("STATIC_PIPELINE", False)}

            def recognize():
                # English-only Whisper rejects explicit task/language options.
                # Transcription is already the model's default task.
                result = model.generate(audio.tolist(), return_timestamps=True, num_beams=beams, **options)
                chunks = result.chunks or []
                if chunks and isinstance(chunks[0], (list, tuple)):
                    chunks = chunks[0]  # ASRPipeline batches; old WhisperPipeline is flat.
                segments = [{"start": float(chunk.start_ts), "end": float(chunk.end_ts),
                             "text": chunk.text} for chunk in chunks]
                return " ".join(result.texts), segments
        else:
            from faster_whisper import WhisperModel

            started = time.perf_counter()
            model = WhisperModel(args.model, device="cpu", compute_type="int8",
                                 cpu_threads=args.threads, local_files_only=True)
            report["load_seconds"] = time.perf_counter() - started
            report["settings"] = {"compute_type": "int8", "cpu_threads": args.threads,
                                  "beam_size": beams, "language": args.language, "vad": True}

            def recognize():
                segments, _ = model.transcribe(audio, language=None if args.language == 'auto' else args.language,
                                               vad_filter=True, beam_size=beams)
                collected = []
                for segment in segments:
                    collected.append({"start": segment.start, "end": segment.end,
                                      "text": segment.text})
                    print(f"  decoded {segment.end:.0f}/{audio_seconds:.0f}s", flush=True)
                return " ".join(item["text"].strip() for item in collected), collected

        save()
        for index in range(args.repeats):
            print(f"Run {index + 1}/{args.repeats}: {audio_seconds:.0f}s audio", flush=True)
            started = time.perf_counter()
            text, segments = recognize()
            elapsed = time.perf_counter() - started
            problems = inspect_transcription(text, segments, audio_seconds)
            report["runs"].append({"seconds": elapsed, "realtime_factor": elapsed / audio_seconds,
                                   "text": text, "segments": segments,
                                   "sanity_problems": problems})
            save()
            print(f"Done: {elapsed:.2f}s; segments={len(segments)}; words={len(text.split())}",
                  flush=True)
            print(f"  beginning: {text[:160]}", flush=True)
            print(f"  ending: {text[-160:]}", flush=True)
            if problems:
                print("  INVALID: " + "; ".join(problems), flush=True)
            else:
                print(f"  sanity checks passed; {audio_seconds / elapsed:.2f}x realtime "
                      "(text still needs verification)", flush=True)
        report["sanity_checks_passed"] = not any(
            item["sanity_problems"] for item in report["runs"])
        if len(report["runs"]) > 1:
            report["warm_median_seconds"] = statistics.median(
                item["seconds"] for item in report["runs"][1:])
        save()
        print(f"Saved: {args.output}")
        if not report["sanity_checks_passed"]:
            raise RuntimeError("Invalid transcription; timings cannot be used as speedup evidence")
    except Exception as exc:
        report["error"] = str(exc)
        save()
        raise


if __name__ == "__main__":
    main()
