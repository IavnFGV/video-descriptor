"""Standalone Torch XPU reproducer: no pyannote, models, audio, or network.

Run with the existing XPU Python. Torch 2.14.1 on Arc 140V produces invalid
all-zero rows for [1, 589] labels, while CPU and batch=2/32 are correct.
Exit 1 means the upstream defect reproduced; this is not a Fast CI test.
"""
import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-workaround', action='store_true',
                        help='Also exercise production conversion with real Torch/pyannote, no weights required')
    args = parser.parse_args()
    import torch

    report = {'torch': torch.__version__, 'device': torch.xpu.get_device_name(), 'cases': []}
    for batch in (1, 2, 32):
        for frames in (16, 589, 590):
            labels = torch.arange(batch * frames, dtype=torch.int64).reshape(batch, frames) % 7
            expected = torch.nn.functional.one_hot(labels, 7)
            actual = torch.nn.functional.one_hot(labels.to('xpu'), 7).cpu()
            report['cases'].append({'batch': batch, 'frames': frames,
                                    'different_elements': int((actual != expected).sum()),
                                    'invalid_rows': int((actual.sum(-1) != 1).sum())})
    if args.check_workaround:
        from pyannote.audio.utils.powerset import Powerset
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows-app'))
        from diarization_worker import cpu_powerset_conversion
        report['workaround'] = []
        for batch in (1, 2, 32):
            # Include silence, one-frame speech, changes, and overlapping classes.
            labels = torch.arange(batch * 589).reshape(batch, 589) % 7
            scores = torch.full((batch, 589, 7), -10.0).scatter_(-1, labels.unsqueeze(-1), 0)
            pipeline = SimpleNamespace(_segmentation=SimpleNamespace(conversion=Powerset(3, 2).to('xpu')))
            cpu_powerset_conversion(pipeline, torch)
            for soft in (False, True):
                actual = pipeline._segmentation.conversion(scores.to('xpu'), soft=soft)
                expected = Powerset(3, 2)(scores, soft=soft)
                report['workaround'].append({'batch': batch, 'soft': soft,
                                             'different_elements': int((actual != expected).sum()),
                                             'output_device': str(actual.device)})
    print(json.dumps(report, indent=2))
    if args.check_workaround:
        return int(any(row['different_elements'] for row in report['workaround']))
    return int(any(row['different_elements'] for row in report['cases']))


if __name__ == '__main__':
    raise SystemExit(main())
