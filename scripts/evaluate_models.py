"""Explicit real-model/prompt regressions. Never invoked by release acceptance."""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from video_descriptor.action_history import record as record_action
from video_descriptor.construction import ARTICLE_PROMPT, PROMPTS, parsed_notes
from video_descriptor.models import Source
from video_descriptor.notes import chat_json
from video_descriptor.ollama_connection import endpoint_url
from video_descriptor.translate import PROMPT as TRANSLATION_PROMPT


def validate_answer(case, answer):
    sources = [Source(**row) for row in case['segments']]
    if case['task'] == 'notes':
        parsed_notes(answer, sources)
    elif case['task'] == 'article':
        if not answer.strip() or re.search(r'\[\d{2,}:[0-5]\d:[0-5]\d\]', answer):
            raise ValueError('Article is empty or contains source timestamp labels')
    elif case['task'] == 'translation':
        expected = [f'[[s{i:04d}]]' for i in range(1, len(sources) + 1)]
        if re.findall(r'\[\[s\d+\]\]', answer) != expected:
            raise ValueError('Translation markers differ from source')
        if re.split(r'\[\[s\d+\]\]', answer)[0].strip():
            raise ValueError('Unexpected text before translation markers')
        if not re.split(r'\[\[s\d+\]\]', answer)[1].strip():
            raise ValueError('Missing first translation text')
    else:
        raise ValueError('Unknown evaluation task')
    normalized = answer.casefold()
    for group in case.get('required_any', []):
        if not any(term.casefold() in normalized for term in group):
            raise ValueError('Missing expected fact: ' + repr(group))
    if any(term.casefold() in normalized for term in case.get('forbidden', [])):
        raise ValueError('Forbidden/hallucinated fact in response')


def material(case):
    lines = []
    for i, row in enumerate(case['segments'], 1):
        n = int(row['start'])
        stamp = f'[{n // 3600:02}:{n // 60 % 60:02}:{n % 60:02}]'
        lines.append((f'[[s{i:04d}]]\n' if case['task'] == 'translation' else stamp + ' Speaker: ') + row['text'])
    return '\n\n'.join(lines)


def run(args):
    base = endpoint_url(args.base_url)
    cases = json.loads(args.cases.read_text(encoding='utf-8'))
    examples = json.loads(args.examples.read_text(encoding='utf-8')) if args.examples else []
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'method': 'real model generation; separate from installer/release acceptance',
              'model': args.model, 'provider': args.provider, 'git_sha': os.environ.get('GITHUB_SHA'),
              'few_shot': bool(examples), 'cases': [], 'status': 'FAIL'}
    if args.provider == 'ollama':
        response = requests.get(base + '/api/tags', timeout=15)
        response.raise_for_status()
        report['identity'] = next(row for row in response.json()['models'] if row['name'] == args.model)
    else:
        from video_descriptor.lmstudio import models
        settings = {'lmstudio_url': base + '/v1'}
        report['identity'] = next(row for row in models(settings) if row['id'] == args.model)
    for case in cases:
        if not re.fullmatch(r'[a-z0-9-]+', case['id']):
            raise ValueError('Invalid case ID')
        prompt = {'notes': PROMPTS['lecture'], 'article': ARTICLE_PROMPT,
                  'translation': TRANSLATION_PROMPT}[case['task']]
        for example in examples:
            if example['task'] == case['task']:
                prompt += '\n\nПример входа:\n' + example['input'] + '\nПравильный ответ:\n' + example['output']
        record = {'id': case['id'], 'task': case['task'], 'status': 'FAIL',
                  'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                  'case_sha256': hashlib.sha256(json.dumps(case, sort_keys=True).encode()).hexdigest()}
        started = time.monotonic()
        answer = ''
        operation = uuid.uuid4().hex

        def event(action, status, stage, operation=operation, case=case):
            record_action(action, folder=args.output, operation_id=operation, request_id=case['id'],
                          model=args.model, task=case['task'], status=status, stage=stage)

        event('operation_started', 'running', 'model_evaluation')
        try:
            event('request_started', 'running', 'generation')
            if args.provider == 'ollama':
                answer = chat_json(prompt, material(case), None, args.model, base, task='construction',
                                   context=8192, output_limit=2048)
            else:
                from video_descriptor.lmstudio import generate
                answer = generate(settings, args.model, prompt, material(case), None, output_tokens=2048)
            event('request_finished', 'done', 'generation')
            event('answer_validation', 'running', 'validation')
            validate_answer(case, answer)
            event('answer_validation', 'done', 'validation')
            record['status'] = 'PASS'
        except (ValueError, RuntimeError, requests.RequestException) as error:
            record['error'] = f'{type(error).__name__}: {error}'
            event('operation_failed', 'error', 'generation_or_validation')
        record['elapsed_seconds'] = round(time.monotonic() - started, 2)
        # Only synthetic versioned evaluation data. Never put responses in common action history.
        event('result_saving', 'running', 'saving')
        (args.output / (case['id'] + '.md')).write_text(answer, encoding='utf-8')
        event('result_saved', 'done', 'saving')
        event('operation_finished', 'done' if record['status'] == 'PASS' else 'error', 'model_evaluation')
        report['cases'].append(record)
        print(f"{case['id']}: {record['status']}", flush=True)
    report['status'] = 'PASS' if report['cases'] and all(row['status'] == 'PASS' for row in report['cases']) else 'FAIL'
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['status'] == 'PASS' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['ollama', 'lmstudio'], default='ollama')
    parser.add_argument('--model', required=True)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--cases', type=Path, default=ROOT / 'tests/model-behavior/cases.json')
    parser.add_argument('--examples', type=Path, help='Optional versioned few-shot examples; compare to baseline without it')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        return run(args)
    except (OSError, ValueError, KeyError, StopIteration, requests.RequestException) as error:
        args.output.mkdir(parents=True, exist_ok=True)
        report = {'status': 'FAIL', 'model': args.model, 'provider': args.provider,
                  'stage': 'evaluation setup', 'error': type(error).__name__, 'cases': []}
        (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('Evaluation setup failed: ' + type(error).__name__, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
