"""Send bounded audio chunks to the Windows NPU worker, with resumable checkpoints."""

import io
import json
import math
import os
import wave

import requests

from .models import Source


def transcribe_remote(audio, start, duration, model, language, log):
    from .media import save_transcription_checkpoint

    base = os.getenv("WHISPER_HTTP_URL", "http://host.docker.internal:8765").rstrip("/")
    try:
        response = requests.get(base + "/health", timeout=(5, 10))
        response.raise_for_status()
        engine = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"Сервис Whisper NPU недоступен: {base}; запустите его в Windows") from exc
    if (engine.get("protocol"), engine.get("device"), engine.get("model")) != (1, "NPU", model):
        raise ValueError("Windows-сервис должен использовать NPU и выбранную Whisper-модель")
    if not engine.get('multilingual') and language not in {"en", "auto"}:
        raise ValueError("Рабочий NPU-сервис base.en поддерживает только английскую речь")
    stat = audio.stat()
    identity = {"audio": str(audio.resolve()), "size": stat.st_size, "mtime": stat.st_mtime_ns,
                "start": start, "duration": duration, "model": model, "language": language,
                "backend": "openvino-http", "engine": engine, "version": 1}
    checkpoint = audio.parent / "transcript.partial.json"
    sources, completed = [], 0.0
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state.get("identity") == identity:
            sources = [Source.model_validate(item) for item in state["sources"]]
            completed = float(state["completed_until"])
            if state.get("done"):
                log("Whisper NPU: результат восстановлен из контрольной точки")
                return sources
            log(f"Whisper NPU: продолжение с {completed:.0f}/{duration:.0f} сек")
    log(f"Whisper NPU: Windows-сервис {base}; FP16/static, по 300 секунд, кэш после каждого блока")
    with wave.open(str(audio), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
            raise ValueError("Для NPU нужен mono PCM16 WAV 16000 Гц")
        total = min(stream.getnframes(), round(duration * 16000))
        offset = round(completed * 16000)
        max_frames = 300 * 16000
        while offset < total:
            count = min(max_frames, total - offset)
            stream.setpos(offset)
            raw = stream.readframes(count)
            payload = io.BytesIO()
            with wave.open(payload, "wb") as target:
                target.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                target.writeframes(raw)
            seconds = count / 16000
            log(f"Whisper NPU: отправлено {offset / 16000:.0f}–{(offset + count) / 16000:.0f} "
                f"сек, видео={seconds:.0f} сек, WAV={len(payload.getvalue())} байт")
            response = requests.post(base + "/transcribe", data=payload.getvalue(),
                                     headers={"Content-Type": "audio/wav", "X-Language": language,
                                              "X-Whisper-Model": model}, timeout=(5, 600))
            if (response.status_code == 500 and "invalid timestamps" in response.text
                    and count > 30 * 16000):
                max_frames = max(30 * 16000, count // 2)
                response.close()
                log(f"Whisper NPU: неверные таймкоды для блока {offset / 16000:.0f}–"
                    f"{(offset + count) / 16000:.0f} сек; повтор с того же места "
                    f"блоком {max_frames / 16000:g} сек. Готовый кэш сохранён")
                continue
            if not response.ok:
                raise RuntimeError(f"Whisper NPU: HTTP {response.status_code}: {response.text[:500]}")
            data = response.json()
            if data.get("engine") != engine or abs(data.get("audio_seconds", -1) - seconds) > .01:
                raise ValueError("Whisper NPU: модель или длительность ответа не совпали с запросом")
            pending = []
            for item in data["segments"]:
                begin, end = float(item["start"]), float(item["end"])
                if not (math.isfinite(begin) and math.isfinite(end)
                        and 0 <= begin <= end <= seconds + .01):
                    raise ValueError("Whisper NPU: неверные таймкоды в ответе")
                pending.append(Source(id=f"s{len(sources) + len(pending) + 1:05d}",
                                      start=start + offset / 16000 + begin,
                                      end=start + offset / 16000 + end, text=item["text"]))
            max_frames = 300 * 16000
            sources.extend(pending)
            offset += count
            completed = offset / 16000
            save_transcription_checkpoint(checkpoint, identity, sources, completed,
                                          done=offset >= total)
            log(f"Whisper NPU: {completed:.0f}/{total / 16000:.0f} сек; "
                f"получено {len(pending)} реплик за {data.get('seconds', 0):.1f} сек; сохранено")
    return sources
