"""Explicit local hardware/API check; does not disable physical devices or call cloud APIs."""
import argparse
import json
import time
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('--url', default='http://127.0.0.1:8780')
    parser.add_argument('--output', type=Path, default=Path('windows-app/runtime/verification/device-api.json'))
    args = parser.parse_args()
    session = requests.Session()
    session.trust_env = False

    def api(path, **kwargs):
        response = session.request(kwargs.pop('method', 'GET'), args.url + path, timeout=30, **kwargs)
        if not response.ok:
            raise RuntimeError(f'{path}: HTTP {response.status_code}: {response.text[:500]}')
        return response.json()

    original = api('/api/compute-settings')['settings']
    instance = api('/health')['instance']
    reports = []
    try:
        for device in ('CPU', 'GPU', 'NPU', 'AUTO'):
            api('/api/compute-settings', method='POST', json={'speech_device': device})
            api('/api/native/prepare', method='POST', headers={'X-App-Instance': instance})
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                snapshot = api('/api/compute-settings')
                chosen = snapshot['selected']
                if snapshot['error']:
                    raise RuntimeError(snapshot['error'])
                if not snapshot['preparing'] and chosen and snapshot['capabilities'][chosen]['ready']:
                    break
                print(device + ': loading model', flush=True)
                time.sleep(2)
            else:
                raise TimeoutError(device + ' preparation timed out')
            started = time.monotonic()
            with args.video.open('rb') as video:
                job = api('/api/upload', method='POST', params={
                    'filename': args.video.name, 'title': f'Проверка устройства · {device}',
                    'engine': 'whisper-local', 'device': device, 'language': 'auto'}, data=video)
            assert job['device_plan']['requested'] == device
            # Editing defaults while a job runs must not change that job's device plan.
            api('/api/compute-settings', method='POST', json={'speech_device': 'AUTO'})
            while time.monotonic() - started < 300:
                status = api('/api/job', params={'id': job['id']})['job']
                if status['status'] in {'done', 'error'}:
                    break
                time.sleep(.3)
            assert status['status'] == 'done', status.get('error')
            assert status['device_plan'] == job['device_plan']
            result = api('/api/speech', params={'job': job['id']})['result']
            assert result['device'] == chosen
            assert result['segments'] and all(0 <= row['start'] <= row['end'] <= result['duration'] + .01
                                              for row in result['segments'])
            exported = session.get(args.url + '/api/subtitles', params={'folder': status['folder'], 'format': 'srt'}, timeout=5)
            exported.raise_for_status()
            assert '-->' in exported.text
            report = {'requested': device, 'selected': chosen, 'actual': result['device'],
                      'audio_seconds': result['duration'], 'elapsed_seconds': round(time.monotonic()-started, 3),
                      'segments': len(result['segments']), 'plan_immutable': True, 'srt_export': True,
                      'engine': job['device_plan']['engine']}
            reports.append(report)
            print(json.dumps(report), flush=True)
        assert reports[-1]['selected'] == 'NPU'
        events = api('/api/native/events')
        assert {'settings_changed', 'device_selected', 'job_started', 'job_finished', 'export'}.issubset({e['action'] for e in events})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'checked_on': '2026-10-17', 'cases': reports,
                                          'physical_devices_disabled': False, 'cloud_used': False,
                                          'history_verified': True}, indent=2), encoding='utf-8')
    finally:
        api('/api/compute-settings', method='POST', json=original)
        session.close()


if __name__ == '__main__':
    main()
