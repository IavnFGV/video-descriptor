"""Sequential comparison using identical input and shared transcription/OCR caches."""

import argparse
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--duration", type=float, default=600)
    parser.add_argument("--model", default="qwen3.5:9b")
    args = parser.parse_args()
    for mode in ("off", "auto"):
        print(f"\nСРАВНЕНИЕ: режим {mode}, {args.duration:.0f} секунд видео", flush=True)
        result = subprocess.run([
            sys.executable, "-u", "-m", "video_descriptor", args.video,
            "--duration", str(args.duration), "--model", args.model, "--vision", mode,
        ], check=False)
        if result.returncode:
            return result.returncode
    print("СРАВНЕНИЕ ЗАВЕРШЕНО. В папке результата: off/metrics.json и auto/metrics.json.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
