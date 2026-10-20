"""Offline quality diagnostics using an EXISTING pyannote environment and weights.

No installation/download. Saves full exclusive/overlapping annotations and stage
arrays. --unpatched-xpu deliberately reproduces upstream one_hot corruption.
Run separately with each managed Python against identical PCM16/16kHz WAV.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import wave
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--device', choices=['cpu', 'xpu'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--unpatched-xpu', action='store_true')
    parser.add_argument('--reference', type=Path, help='Optional RTTM; score entire input with collar=0, overlaps included')
    parser.add_argument('--uri', help='RTTM recording ID')
    args = parser.parse_args()
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYANNOTE_METRICS_ENABLED='0')
    import numpy as np
    import torch
    from pyannote.audio import Pipeline

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows-app'))
    from diarization_worker import cpu_powerset_conversion

    torch.set_num_threads(4)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    artifacts = args.output.with_suffix('.arrays')
    artifacts.mkdir(exist_ok=True)
    started = time.monotonic()
    pipeline = Pipeline.from_pretrained(str(args.model))
    pipeline.to(torch.device(args.device))
    if args.device == 'xpu' and not args.unpatched_xpu:
        cpu_powerset_conversion(pipeline, torch)
    if args.device == 'xpu':
        torch.xpu.synchronize()
    load_seconds = time.monotonic() - started
    with wave.open(str(args.audio)) as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
            raise ValueError('Expected mono PCM16 WAV at 16000 Hz; no implicit resampling')
        raw = audio.readframes(audio.getnframes())
    signal = torch.from_numpy(np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768).unsqueeze(0)
    stages, modules = {}, {}

    def capture(name):
        def record(module, inputs, output):
            if isinstance(output, tuple):
                output = output[0]
            array = output.detach().cpu().numpy()
            modules.setdefault(name, []).append({'shape': list(array.shape), 'device': str(output.device),
                                                 'dtype': str(output.dtype), 'finite': int(np.isfinite(array).sum()),
                                                 'size': array.size})
            # Last batch retained; short A has exactly one batch, useful for isolation.
            np.save(artifacts / ('module-' + name + '.npy'), array)
        return record

    for name in ('sincnet', 'lstm', 'classifier', 'activation'):
        module = getattr(pipeline._segmentation.model, name, None)
        if module is not None:
            module.register_forward_hook(capture(name))
    pipeline._embedding.model_.register_forward_hook(capture('embedding'))

    def hook(name, artifact, **kwargs):
        if artifact is None:
            return
        array = artifact if isinstance(artifact, np.ndarray) else getattr(artifact, 'data', None)
        if isinstance(array, np.ndarray):
            np.save(artifacts / (name + '.npy'), array)
            stages[name] = {'shape': list(array.shape), 'dtype': str(array.dtype),
                            'finite': int(np.isfinite(array).sum()), 'size': array.size}

    started = time.monotonic()
    prediction = pipeline({'waveform': signal, 'sample_rate': 16000}, hook=hook)
    if args.device == 'xpu':
        torch.xpu.synchronize()
    inference_seconds = time.monotonic() - started

    def turns(annotation):
        return [{'start': float(s.start), 'end': float(s.end), 'duration': float(s.duration), 'speaker': str(k)}
                for s, k in annotation]

    report = {'device': args.device, 'torch': torch.__version__, 'duration': len(raw) / 32000,
              'pcm_sha256': hashlib.sha256(raw).hexdigest(), 'load_seconds': load_seconds,
              'inference_seconds': inference_seconds, 'unpatched_xpu': args.unpatched_xpu,
              'stages': stages, 'modules': modules, 'turns': turns(prediction.exclusive_speaker_diarization),
              'regular_turns': turns(prediction.speaker_diarization)}
    if args.reference:
        from pyannote.core import Segment, Timeline
        from pyannote.database.util import load_rttm
        from pyannote.metrics.diarization import DiarizationErrorRate
        reference = load_rttm(args.reference)[args.uri].crop(Segment(0, report['duration']))
        metric = DiarizationErrorRate(collar=0, skip_overlap=False)
        report['der'] = metric(reference, prediction.exclusive_speaker_diarization,
                               uem=Timeline([Segment(0, report['duration'])]), detailed=True)
        report['der_mapping'] = metric.optimal_mapping(reference, prediction.exclusive_speaker_diarization)
        report['der_parameters'] = {'collar': 0, 'skip_overlap': False, 'mapping': 'optimal Hungarian',
                                    'uem': [0, report['duration']]}
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'turns': len(report['turns'])}))


if __name__ == '__main__':
    main()
