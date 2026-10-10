"""Replay two saved text translations against Gemini without changing lecture artifacts."""

import argparse
import html
import json
import os
import re
import time
from pathlib import Path

import requests

RATES = {"gemini-3.5-flash-lite": (0.30, 2.50),
         "gemini-3.1-flash-lite": (0.25, 1.50), "gemini-3.8-flash": (0.75, 3.75)}


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def select_samples(folder):
    selected = []
    chunks = set()
    for path in sorted(folder.glob("*-translate-*"), reverse=True):
        if not (path / "result.json").exists():
            continue
        result = json.loads((path / "result.json").read_text())
        if result.get("status") != "complete":
            continue
        request = json.loads((path / "request.json").read_text())
        payload = request["payload"]
        if payload.get("format") or not re.search(r"\[\[s\d+\]\]",
                                                  payload["messages"][-1]["content"]):
            continue
        chunk = request["context"].get("chunk", path.name)
        if chunk in chunks:
            continue
        chunks.add(chunk)
        events = [json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()]
        end = next((event for event in reversed(events) if event.get("done")), {})
        selected.append({"journal": str(path), "chunk": chunk, "payload": payload,
                         "local_text": (path / "response.txt").read_text(),
                         "local_seconds": (end.get("total_duration", 0) / 1e9) or None})
        if len(selected) == 2:
            break
    if len(selected) != 2:
        raise ValueError("Нужны два завершённых запроса перевода с метками")
    return selected[::-1]


def marker_check(source, answer):
    expected = re.findall(r"\[\[s\d+\]\]", source)
    found = re.findall(r"\[\[s\d+\]\]", answer)
    parts = re.split(r"\[\[s\d+\]\]", answer)
    return {"valid": found == expected and not parts[0].strip()
            and len(parts) > 1 and bool(parts[1].strip()),
            "expected": len(expected), "received": len(found),
            "empty_markers": [m for m, text in zip(found, parts[1:]) if not text.strip()]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requests", type=Path, help="Папка requests результата лекции")
    parser.add_argument("--model", choices=RATES, default="gemini-3.5-flash-lite")
    parser.add_argument("--output", type=Path, default=Path("output/gemini-translation-probe"))
    parser.add_argument("--env-file", type=Path, default=Path(".env.gemini"))
    parser.add_argument("--run", action="store_true", help="Отправить два запроса Google")
    parser.add_argument("--paid-project", action="store_true",
                        help="Ключ принадлежит проекту с активным платным billing")
    args = parser.parse_args()
    samples_file = args.output / "samples.json"
    args.output.mkdir(parents=True, exist_ok=True)
    samples = (json.loads(samples_file.read_text()) if samples_file.exists()
               else select_samples(args.requests))
    write(samples_file, samples)
    print(f"Подготовлены {len(samples)} запроса. Модель: {args.model}", flush=True)
    if not args.run:
        print(f"Ничего не отправлено. Материал для проверки: {samples_file}")
        return
    if not args.paid_project:
        parser.error("Проверьте Paid/Tier 1 у проекта ключа и добавьте --paid-project. "
                     "По API-ключу этот скрипт не может проверить billing.")
    key = os.getenv("GEMINI_API_KEY", "")
    if not key and args.env_file.exists():
        for line in args.env_file.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                key = line.partition("=")[2].strip().strip("\"'")
    if not key:
        parser.error("Добавьте GEMINI_API_KEY в .env.gemini или окружение")
    results = []
    for index, sample in enumerate(samples, 1):
        target = args.output / f"{args.model}-{index}.json"
        if target.exists():
            print(f"Запрос {index}: результат уже сохранён, повторного расхода нет")
            results.append(json.loads(target.read_text()))
            continue
        messages = sample["payload"]["messages"]
        config = {"temperature": 0, "maxOutputTokens": 4096,
                  "responseMimeType": "text/plain"}
        if args.model != "gemini-3.1-flash-lite":
            config["thinkingConfig"] = {"thinkingLevel": "minimal" if
                                        args.model == "gemini-3.5-flash-lite" else "low"}
        payload = {"systemInstruction": {"parts": [{"text": messages[0]["content"]}]},
                   "contents": [{"role": "user", "parts": [{"text": messages[-1]["content"]}]}],
                   "generationConfig": config}
        write(args.output / f"{args.model}-{index}-request.json", payload)
        print(f"Запрос {index}/2, блок {sample['chunk']}: отправляем только текст", flush=True)
        started = time.monotonic()
        # Key stays in a header; no retries to avoid unintended duplicate billing.
        try:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{args.model}:generateContent",
                headers={"x-goog-api-key": key}, json=payload, timeout=(10, 180))
        except requests.RequestException:
            raise SystemExit("Ошибка соединения. Автоповтора нет; запрос мог быть оплачен.") from None
        seconds = time.monotonic() - started
        if not response.ok:
            safe_error = response.text.replace(key, "[REDACTED]")
            (args.output / f"{args.model}-{index}-error.txt").write_text(safe_error)
            raise SystemExit(f"Gemini HTTP {response.status_code}; подробности в файле ошибки")
        data = response.json()
        candidate = (data.get("candidates") or [{}])[0]
        text = "".join(part.get("text", "") for part in
                       candidate.get("content", {}).get("parts", []) if not part.get("thought"))
        usage = data.get("usageMetadata", {})
        input_tokens = usage.get("promptTokenCount")
        output_tokens = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
        input_rate, output_rate = RATES[args.model]
        cost = ((input_tokens * input_rate + output_tokens * output_rate) / 1e6
                if input_tokens is not None else None)
        result = {"chunk": sample["chunk"], "model": args.model, "seconds": round(seconds, 3),
                  "local_seconds": sample["local_seconds"], "text": text,
                  "marker_check": marker_check(messages[-1]["content"], text),
                  "finish_reason": candidate.get("finishReason"), "estimated_usd": cost,
                  "rates_usd_per_million": RATES[args.model], "raw_response": data}
        write(target, result)
        results.append(result)
        print(f"Готово: {seconds:.2f} сек, оценка ${cost or 0:.6f}; "
              f"метки: {result['marker_check']}", flush=True)
    write(args.output / f"{args.model}-summary.json", results)
    page = ["<!doctype html><meta charset='utf-8'><title>Сравнение перевода</title>",
            ("<style>body{font:16px sans-serif;margin:30px}article{display:grid;"
            "grid-template-columns:repeat(3,1fr);gap:20px}pre{white-space:pre-wrap}</style>")]
    for sample, result in zip(samples, results):
        page.append(f"<h2>Блок {html.escape(sample['chunk'])}: Qwen {sample['local_seconds']} сек / "
                    f"Gemini {result['seconds']} сек, ≈ ${result['estimated_usd']}</h2><article>")
        for title, text in [("Исходник", sample["payload"]["messages"][-1]["content"]),
                            ("Qwen", sample["local_text"]), ("Gemini", result["text"])]:
            page.append(f"<section><h3>{title}</h3><pre>{html.escape(text)}</pre></section>")
        page.append("</article>")
    (args.output / f"{args.model}.html").write_text("".join(page), encoding="utf-8")


if __name__ == "__main__":
    main()
