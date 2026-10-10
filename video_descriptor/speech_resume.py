"""Recover stopped NPU transcription while the existing GPU diarization keeps running."""
import fcntl
import hashlib
import sys
import time
from pathlib import Path

from .jobs import read_json, start_worker, write_json
from .speech import group_words
from .speech_npu import transcribe


def main(job_file):
    root = Path.cwd()
    job = read_json(job_file)
    folder = root / 'output' / job['folder']
    result = read_json(folder / 'speech.json')
    if (job['status'] != 'running' or job['engine'] != 'whisper-npu-diarization-xpu'
            or not result.get('parallel', {}).get('transcription', '').startswith('NPU остановлен:')):
        raise RuntimeError('Recovery requires stopped NPU transcription and an existing GPU run')
    with (job_file.parent / 'npu-recovery.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        video = Path(job['video']).resolve()
        stat = video.stat()
        identity = hashlib.sha256(f'{video}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()[:16]
        audio = root / 'output' / ('speech-audio-' + identity) / 'audio.wav'
        recovery = {'status': 'running', 'job_started': job['started'],
                    'message': 'NPU: продолжение с VAD', 'processed': result['processed'],
                    'segments': result['segments']}

        def log(message):
            recovery['message'] = message
            write_json(folder / 'npu-recovery.json', recovery)
            print(time.strftime('%H:%M:%S'), message, flush=True)

        def on_chunk(items, processed):
            recovery.update(processed=processed, segments=group_words(items))
            log(f'NPU + VAD: сохранено {processed:.0f}/{result["duration"]:.0f} сек')

        try:
            words, timing = transcribe(audio, folder, on_chunk, log)
        except Exception as exc:
            recovery['status'] = 'error'
            log(f'NPU + VAD: ошибка: {exc}')
            raise
        write_json(folder / 'words.json', words)
        recovery.update(status='done', timing=timing)
        log('NPU + VAD готов · ожидаем сохранения GPU, чтобы объединить результаты')
        while True:
            current = read_json(job_file)
            if current.get('started') != job['started']:
                return
            if current['status'] == 'error':
                if not (folder / 'diarization.json').exists():
                    log('GPU завершился без готового кэша; продолжение доступно вручную')
                    return
                current.update(status='queued', error=None)
                write_json(job_file, current)
                start_worker(root)
                log('Задание продолжено: готовые NPU и GPU результаты будут взяты из кэша')
                return
            if current['status'] == 'done':
                return
            time.sleep(2)


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
