"""Explicit local end-to-end checks. Uses existing media/models; no cloud calls."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import app
import requests


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    args = parser.parse_args()
    settings = app.config()
    base = f'http://127.0.0.1:{settings["port"]}'
    session = requests.Session()
    session.trust_env = False
    before = session.get(base + '/health', timeout=5).json()
    doctor = session.get(base + '/api/doctor', timeout=10).json()
    if not doctor['npu']['ready']:
        raise RuntimeError('NPU not ready; start the existing worker first')
    folder = app.HERE / 'runtime' / 'verification' / time.strftime('%Y%m%d-%H%M%S')
    folder.mkdir(parents=True)
    ffmpeg = app.ffmpeg_path()
    results = []
    for name, seconds in [('short', 20), ('long', 900), ('silence', 30)]:
        target = folder / f'{name}.mp4'
        command = [ffmpeg, '-v', 'error', '-y']
        if name == 'silence':
            command += ['-f', 'lavfi', '-i', 'color=c=black:s=320x180:r=1',
                        '-f', 'lavfi', '-i', 'anullsrc=r=16000:cl=mono', '-t', str(seconds),
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', str(target)]
        else:
            command += ['-i', str(args.video.resolve()), '-t', str(seconds),
                        '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy', '-c:a', 'aac',
                        '-b:a', '64k', str(target)]
        subprocess.run(command, check=True, creationflags=0x08000000 if os.name == 'nt' else 0)
        started = time.monotonic()
        with target.open('rb') as stream:
            response = session.post(base + '/api/upload', params={
                'filename': target.name, 'title': f'{name} · проверка Windows',
                'mode': 'audio', 'engine': 'whisper-npu', 'speech_only': 'true', 'language': 'auto'},
                data=stream, timeout=20)
        response.raise_for_status()
        job = response.json()
        print(f'{name}: uploaded, job={job["id"]}', flush=True)
        last_notice = 0
        stop_refused = False
        while time.monotonic() - started < 1800:
            job = session.get(base + '/api/job', params={'id': job['id']}, timeout=5).json()['job']
            if name == 'long' and not stop_refused and job['status'] in {'queued', 'running'}:
                refused = session.post(base + '/api/native/stop', headers={'X-App-Instance': before['instance']}, timeout=5)
                assert refused.status_code == 409
                stop_refused = True
            if job['status'] in {'done', 'error'}:
                break
            if time.monotonic() - last_notice > 15:
                print(f'{name}: {job["status"]}, elapsed={time.monotonic()-started:.1f}s', flush=True)
                last_notice = time.monotonic()
            time.sleep(1)
        assert job['status'] == 'done', job
        data = session.get(base + '/api/speech', params={'job': job['id']}, timeout=5).json()['result']
        assert data['status'] == 'done'
        segments = data['segments']
        ids = [row['id'] for row in segments]
        assert len(ids) == len(set(ids))
        assert all(0 <= row['start'] <= row['end'] <= data['duration'] + .01 for row in segments)
        assert (not segments) if name == 'silence' else bool(segments)
        assert data.get('no_speech') == (name == 'silence')
        for format in ['srt', 'vtt']:
            exported = session.get(base + '/api/subtitles', params={'folder': job['folder'], 'format': format}, timeout=5)
            exported.raise_for_status()
            (folder / f'{name}.{format}').write_bytes(exported.content)
            assert ('WEBVTT' in exported.text) if format == 'vtt' else ('-->' in exported.text or name == 'silence')
        result = {'case': name, 'job': job['id'], 'media_sha256': checksum(target),
                  'audio_seconds': data['duration'], 'segments': len(segments),
                  'elapsed_seconds': round(time.monotonic() - started, 2),
                  'valid_timestamps': True, 'unique_ids': True, 'no_speech': data.get('no_speech'),
                  'busy_stop_refused': stop_refused}
        if name == 'short':
            original_file = Path(settings['workspace']) / 'output' / job['folder'] / 'speech.json'
            original_hash = checksum(original_file)
            row = segments[0]
            end = row['end'] - .01 if row['end'] - row['start'] > .1 else row['end']
            changes = {'folder': job['folder'], 'index': 0, 'revision': data['edit_revision'],
                       'action': 'edit', 'text': row['text'] + ' [проверено]',
                       'speaker': row['speaker'], 'start': row['start'], 'end': end}
            edited = session.post(base + '/api/speech-edit', json=changes, timeout=5)
            edited.raise_for_status()
            assert edited.json()['segments'][0]['id'] == row['id']
            assert checksum(original_file) == original_hash
            stale = session.post(base + '/api/speech-edit', json=changes, timeout=5)
            assert stale.status_code == 400
            text = session.get(base + '/api/subtitles', params={'folder': job['folder'], 'format': 'srt'}, timeout=5).text
            assert '[проверено]' in text
            # Simulate failure during job finalization; the completed speech must survive retry.
            file = Path(settings['workspace']) / 'output/jobs' / job['id'] / 'job.json'
            saved = json.loads(file.read_text(encoding='utf-8'))
            file.write_text(json.dumps({**saved, 'status': 'error', 'error': 'verification: finalization interrupted'}), encoding='utf-8')
            retried = session.post(base + '/api/retry', params={'id': job['id']}, timeout=5)
            retried.raise_for_status()
            for _ in range(40):
                state = session.get(base + '/api/job', params={'id': job['id']}, timeout=5).json()['job']
                if state['status'] == 'done':
                    break
                time.sleep(.25)
            assert state['status'] == 'done'
            assert checksum(original_file) == original_hash
            result.update(edit_and_export=True, original_immutable=True, stale_edit_rejected=True,
                          retry_keeps_completed_speech=True)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    repeated = subprocess.run([sys.executable, str(app.HERE / 'app.py'), '--no-browser'],
                              capture_output=True, text=True, encoding='utf-8', timeout=15, check=False)
    assert repeated.returncode == 0, repeated.stderr
    after = session.get(base + '/health', timeout=5).json()
    assert before['instance'] == after['instance']
    report = {'checked_on': '2026-10-16', 'platform': sys.platform,
              'source_video_name': args.video.name, 'engine': doctor['npu']['details'],
              'cases': results, 'repeat_launch_same_instance': True,
              'cloud_used': False, 'gpu_diarization_tested': False,
              'notes_translation_tested': False}
    (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Report: ' + str(folder / 'report.json'), flush=True)


if __name__ == '__main__':
    main()
