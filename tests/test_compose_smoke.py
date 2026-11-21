import json
from unittest.mock import Mock

import pytest

from scripts.smoke_compose import read_container_json


def test_smoke_reads_private_worker_json_inside_container(monkeypatch):
    def reject_host_read(*args, **kwargs):
        raise PermissionError('worker files belong to the container UID')

    monkeypatch.setattr('pathlib.Path.read_text', reject_host_read)
    compose = Mock(return_value=json.dumps({'status': 'error', 'error': 'Распознавание'}))
    path = '/workspace/output/jobs/with space/job.json'
    result = read_container_json(compose, path)
    assert result == {'status': 'error', 'error': 'Распознавание'}
    arguments = compose.call_args.args
    assert arguments[:5] == ('exec', '-T', 'app', 'python', '-c')
    assert arguments[-1] == path


def test_smoke_rejects_invalid_worker_json():
    with pytest.raises(json.JSONDecodeError):
        read_container_json(Mock(return_value='not json'), '/workspace/output/jobs/test/job.json')
