"""Audio/Whisper approach adapted from IavnFGV/reels-analyzer media.py.

Unlike the short-video pipeline, retain every segment and its source timestamps.
"""

import json
import math
import os
import shutil
import subprocess
import wave
from pathlib import Path

from .models import Source


def run(command: list[str]) -> str:
    if command[0] == 'ffmpeg' and not shutil.which('ffmpeg') and not os.getenv('VIDEO_DESCRIPTOR_FFMPEG'):
        try:
            import imageio_ffmpeg
            command = [imageio_ffmpeg.get_ffmpeg_exe(), *command[1:]]
        except ImportError:
            raise RuntimeError('FFmpeg не найден; подготовьте Windows-окружение приложения') from None
    if command[0] == 'ffmpeg' and os.getenv('VIDEO_DESCRIPTOR_FFMPEG'):
        command = [os.environ['VIDEO_DESCRIPTOR_FFMPEG'], *command[1:]]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', check=False,
                            **({'creationflags': 0x08000000} if os.name == 'nt' else {}))
    if result.returncode:
        raise RuntimeError(f"{command[0]}: {result.stderr.strip()[-2000:]}")
    return result.stdout


def probe(video: Path) -> dict:
    if not shutil.which('ffprobe'):
        # The Windows FFmpeg wheel has no ffprobe; PyAV is already a dependency.
        import av
        with av.open(str(video)) as container:
            if container.duration is None:
                raise ValueError('Не удалось определить длительность записи')
            return {'format': {'duration': str(container.duration / av.time_base)},
                    'streams': [{'codec_type': stream.type} for stream in container.streams]}
    return json.loads(run([
        "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(video)
    ]))


def extract_audio(video: Path, target: Path, start: float, duration: float) -> None:
    temporary = target.with_suffix(".tmp.wav")
    run([
        "ffmpeg", "-v", "error", "-y", "-ss", str(start), "-i", str(video),
        "-t", str(duration), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(temporary),
    ])
    temporary.replace(target)


def save_transcription_checkpoint(path: Path, identity: dict, sources: list[Source],
                                  completed_until: float, done: bool = False):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump({"identity": identity, "sources": [source.model_dump() for source in sources],
                   "completed_until": completed_until, "done": done}, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def audio_tail(audio: Path, offset: float):
    """Read only the remaining part of our mono 16 kHz PCM audio."""
    import numpy as np

    with wave.open(str(audio), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
            raise ValueError("Для продолжения Whisper нужен mono PCM16 WAV с частотой 16000 Гц")
        stream.setpos(min(round(offset * 16000), stream.getnframes()))
        data = stream.readframes(stream.getnframes() - stream.tell())
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def transcribe(audio: Path, start: float, duration: float, model: str, language: str, log):
    backend = os.getenv("WHISPER_BACKEND", "faster-whisper")
    if backend == "openvino-http":
        from .whisper_http import transcribe_remote
        return transcribe_remote(audio, start, duration, model, language, log)
    if backend != "faster-whisper":
        raise ValueError(f"Неизвестный WHISPER_BACKEND: {backend}")
    from faster_whisper import WhisperModel

    device = os.getenv("WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    stat = audio.stat()
    identity = {"audio": str(audio.resolve()), "size": stat.st_size, "mtime": stat.st_mtime_ns,
                "start": start, "duration": duration, "model": model, "language": language,
                "device": device, "compute_type": compute_type, "version": 1}
    checkpoint = audio.parent / "transcript.partial.json"
    sources, resume = [], 0.0
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state.get("identity") == identity:
            saved = [Source.model_validate(item) for item in state["sources"]]
            if state.get("done"):
                log("Whisper: распознавание завершено ранее, восстановлено из контрольной точки")
                return saved
            # Redecode a short tail, aligned to a saved utterance, to preserve boundary speech.
            cutoff = max(0, state["completed_until"] - 30)
            sources = [source for source in saved if source.end - start <= cutoff]
            redo = saved[len(sources):]
            resume = max(0, redo[0].start - start) if redo else cutoff
            log(f"Whisper: продолжение с {resume:.1f}/{duration:.1f} сек; "
                f"сохранено {len(sources)} реплик, конец повторно проверяется")
        else:
            log("Whisper: параметры изменились, промежуточный кэш не подходит")
    log(f"Whisper: загрузка {model}; при первом запуске скачиваются веса")
    whisper = WhisperModel(
        model, device=device, compute_type=compute_type,
        cpu_threads=min(8, os.cpu_count() or 1),
    )
    log("Whisper: модель готова, распознавание началось")
    input_audio = audio_tail(audio, resume) if resume else str(audio)
    segments, info = whisper.transcribe(input_audio,
                                       language=None if language == "auto" else language,
                                       vad_filter=True)
    for segment in segments:
        if segment.text.strip():
            sources.append(Source(
                id=f"s{len(sources) + 1:05d}", start=start + resume + segment.start,
                end=min(start + duration, start + resume + segment.end), text=segment.text.strip(),
            ))
        completed_until = min(duration, resume + segment.end)
        save_transcription_checkpoint(checkpoint, identity, sources, completed_until)
        log(f"Whisper: {min(100, completed_until / duration * 100):.0f}% "
            f"({completed_until:.0f}/{duration:.0f} сек), сегментов: {len(sources)}; сохранено")
    save_transcription_checkpoint(checkpoint, identity, sources, duration, done=True)
    log(f"Whisper: завершено; язык: {info.language}, сегментов: {len(sources)}")
    return sources


def extract_frames(video: Path, folder: Path, start: float, duration: float,
                   interval: float, language: str, log, *, strategy="interval",
                   scan_interval=1.0, threshold=0.01, max_gap=60.0):
    if strategy == "scene":
        from .frames import extract_scene_frames
        return extract_scene_frames(video, folder, start, duration, language, log,
                                    scan_interval, threshold, max_gap)
    if strategy != "interval":
        raise ValueError(f"Неизвестная стратегия кадров: {strategy}")
    import cv2

    folder.mkdir(exist_ok=True)
    capture = cv2.VideoCapture(str(video))
    sources = []
    total = math.ceil(duration / interval)
    try:
        for index in range(total):
            timestamp = start + index * interval
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"Не удалось прочитать кадр на {timestamp:.1f} сек")
            image = folder / f"f{index + 1:05d}.jpg"
            if not cv2.imwrite(str(image), frame):
                raise RuntimeError(f"Не удалось сохранить {image}")
            text = run(["tesseract", str(image), "stdout", "-l", language, "--psm", "11"])
            sources.append(Source(
                id=image.stem, start=timestamp, end=min(start + duration, timestamp + interval),
                text=text.strip(), image=f"frames/{image.name}",
            ))
            from .frames import save_frame_checkpoint
            save_frame_checkpoint(folder, sources)
            log(f"Экран/OCR: {index + 1}/{total} кадров ({(index + 1) / total * 100:.0f}%)")
    finally:
        capture.release()
    return sources
