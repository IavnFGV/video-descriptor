"""Compare plain marker translation on failed subtitle batches; keep results separate."""

import argparse
import json
import re
import time
from pathlib import Path

import requests

from video_descriptor.models import Source
from video_descriptor.notes import group_sources

PROMPT = (Path(__file__).resolve().parents[1] / "video_descriptor" / "prompts"
          / "translate_markers_ru.txt").read_text(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output/translation-marker-probe"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sources = [Source.model_validate(x) for x in json.loads(
        (args.folder / "transcript.json").read_text())]
    groups = group_sources(sources, 0, 90)
    failed = json.loads((args.folder / "translation-errors.json").read_text())
    blocks = sorted({x["block"] for x in failed})[:6]
    results = []
    for block in blocks:
        group = groups[block - 1]
        markers = [f"[[s{i:04d}]]" for i in range(1, len(group) + 1)]
        content = "\n\n".join(f"{m}\n{s.text}" for m, s in zip(markers, group))
        payload = {
            "model": "qwen3.5:9b", "stream": False, "think": False,
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 4096},
            "messages": [{"role": "system", "content": PROMPT},
                         {"role": "user", "content": content}],
        }
        target = args.output / f"block-{block:03d}.json"
        record = {"block": block, "request": payload,
                  "source_ids": [s.id for s in group]}
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        print(f"Block {block}: sending {len(group)} replicas", flush=True)
        started = time.monotonic()
        try:
            response = requests.post("http://host.docker.internal:11434/api/chat",
                                     json=payload, timeout=(10, 900))
            response.raise_for_status()
            data = response.json()
            record["response"] = data
            text = data["message"]["content"]
            found = re.findall(r"\[\[s\d+\]\]", text)
            pieces = re.split(r"\[\[s\d+\]\]", text)
            valid = (found == markers and not pieces[0].strip()
                     and bool(pieces[1].strip())
                     and data.get("done_reason") != "length")
            record["valid"] = valid
            record["translations"] = (dict(zip(record["source_ids"],
                [x.strip() for x in pieces[1:]])) if valid else {})
            record["found_markers"] = found
            record["empty_markers"] = [m for m, part in zip(found, pieces[1:])
                                       if not part.strip()]
        except (requests.RequestException, KeyError, ValueError) as exc:
            record.update(valid=False, error=str(exc))
        record["seconds"] = round(time.monotonic() - started, 2)
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        summary = {k: record[k] for k in ("block", "valid", "seconds")}
        results.append(summary)
        (args.output / "summary.json").write_text(json.dumps(results, indent=2))
        print(summary, flush=True)


if __name__ == "__main__":
    main()
