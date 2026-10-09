"""Process complete videos sequentially, then translate their subtitles."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def result_folder(output: Path, video: Path) -> Path:
    candidates = []
    for folder in output.iterdir():
        manifest = folder / "manifest.json"
        if not manifest.is_file():
            continue
        data = json.loads(manifest.read_text())
        if (data.get("video") == str(video.resolve()) and data.get("start") == 0
                and data.get("duration") is None):
            candidates.append(folder)
    if not candidates:
        raise RuntimeError(f"Не найдена папка результата для {video}")
    return max(candidates, key=lambda folder: (folder / "manifest.json").stat().st_mtime_ns)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("videos", nargs="*", type=Path,
                        help="Файлы видео; по умолчанию все видео из data/")
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--vision", choices=["auto", "off"], default="auto")
    parser.add_argument("--frame-strategy", choices=["scene", "interval"], default="scene")
    parser.add_argument("--scan-interval", type=float, default=1)
    parser.add_argument("--scene-threshold", type=float, default=0.01)
    parser.add_argument("--max-frame-gap", type=float, default=60)
    parser.add_argument("--frame-interval", type=float, default=15)
    parser.add_argument("--chunk-strategy", choices=["time", "slides"])
    parser.add_argument("--chunk-seconds", type=float, default=180)
    parser.add_argument("--max-chunk-seconds", type=float, default=600)
    parser.add_argument("--max-chunk-chars", type=int, default=18000)
    parser.add_argument("--min-chunk-seconds", type=float, default=180)
    parser.add_argument("--preserve-blocks", type=int, default=0)
    parser.add_argument("--slide-similarity", type=float, default=0.55)
    parser.add_argument("--without-context", action="store_true")
    parser.add_argument("--think", action="store_true")
    parser.add_argument("--reuse-completed-blocks", action="store_true")
    parser.add_argument("--without-translation", action="store_true")
    args = parser.parse_args()
    videos = args.videos or sorted(path for path in Path("data").iterdir()
                                  if path.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm"})
    videos = list(dict.fromkeys(videos))
    if not videos:
        parser.error("Положите видео в data/ или укажите файлы аргументами")
    for video in videos:
        if not video.is_file():
            parser.error(f"Видео не найдено: {video}")
    for index, video in enumerate(videos, 1):
        print(f"\n=== Видео {index}/{len(videos)}: {video.name} ===", flush=True)
        code = subprocess.run([
            sys.executable, "-u", "-m", "video_descriptor", str(video),
            "--model", args.model, "--vision", args.vision,
            "--frame-strategy", args.frame_strategy,
            "--scan-interval", str(args.scan_interval),
            "--scene-threshold", str(args.scene_threshold),
            "--max-frame-gap", str(args.max_frame_gap),
            "--frame-interval", str(args.frame_interval),
            "--chunk-seconds", str(args.chunk_seconds),
            "--max-chunk-seconds", str(args.max_chunk_seconds),
            "--max-chunk-chars", str(args.max_chunk_chars),
            "--min-chunk-seconds", str(args.min_chunk_seconds),
            "--preserve-blocks", str(args.preserve_blocks),
            "--slide-similarity", str(args.slide_similarity),
            *(["--chunk-strategy", args.chunk_strategy] if args.chunk_strategy else []),
            *(["--without-context"] if args.without_context else []),
            *(["--think"] if args.think else []),
            *(["--reuse-completed-blocks"] if args.reuse_completed_blocks else []),
        ], check=False).returncode
        if code:
            return code
        folder = result_folder(Path("output"), video)
        if not args.without_translation:
            print(f"=== Перевод: {video.name} ===", flush=True)
            code = subprocess.run([
                sys.executable, "-u", "-m", "video_descriptor.translate", str(folder),
                "--model", args.model,
            ], check=False).returncode
            if code:
                return code
        print(f"ГОТОВО {index}/{len(videos)}: {folder / 'report.html'}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nОстановлено. Повтор той же команды продолжит из кэша.", flush=True)
        raise SystemExit(130) from None
