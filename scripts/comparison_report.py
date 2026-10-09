"""Write a readable comparison from completed, fresh run metrics."""

import argparse
import json
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--preparation-overlap", action="store_true")
    args = parser.parse_args()
    modes = {mode: json.loads((args.folder / mode / "metrics.json").read_text())
             for mode in ("off", "auto")}
    duration = modes["off"]["processed_seconds"]
    if modes["auto"]["processed_seconds"] != duration:
        raise ValueError("Нельзя сравнивать разные фрагменты")
    if any(data.get("cached_blocks", 0) for data in modes.values()):
        raise ValueError("Прогон из кэша не измеряет скорость модели")
    log = (args.folder / "run.log").read_text()
    preparation = []
    for stage in (2, 3):
        match = re.search(rf"\[{stage}/5\].*готово, ([\d.]+) сек", log)
        preparation.append(float(match[1]) if match else 0)
    text = ["# Сравнение анализа лекции", "",
            f"Один и тот же фрагмент: {duration / 60:.0f} минут. Запуски последовательные.", "",
            f"Общая подготовка: Whisper {preparation[0]:.1f} сек, OCR {preparation[1]:.1f} сек.", "",
            "| Вариант | Анализ, мин | Отправлено картинок | Запросов модели |",
            "|---|---:|---:|---:|"]
    for mode, data in modes.items():
        label = "OCR + речь" if mode == "off" else "OCR + речь + выборочный осмотр"
        text.append(f"| {label} | {data['analysis_seconds'] / 60:.1f} | "
                    f"{data['images_sent']} | {len(data['calls'])} |")
    ratio = modes["auto"]["analysis_seconds"] / modes["off"]["analysis_seconds"]
    text.extend(["", f"Отношение времени auto/off: {ratio:.2f}.", "",
                 "## Оценка часовой лекции", "",
                 "Линейная оценка при похожем материале и неизменной нагрузке компьютера:", ""])
    for mode, data in modes.items():
        hours = (data["analysis_seconds"] + sum(preparation)) * 3600 / duration / 3600
        text.append(f"- {mode}: примерно {hours:.1f} часа вместе с подготовкой.")
    text.extend(["", ("Это ориентир, а не гарантия. Число выбранных кадров, сложность слайдов, "
                      "длина конспекта, прогрев модели и нагрузка компьютера меняют время."), ""])
    if args.preparation_overlap:
        text.extend([("Первый текстовый блок выполнялся одновременно с подготовкой отдельного "
                      "фрагмента квиза; это могло повлиять на его скорость."), ""])
    text.extend([
                 "Качество сравнивать по самим источникам, а не по числу пунктов.", "",
                 "- [OCR + речь](off/report.html)",
                 "- [Гибридный анализ](auto/report.html)", ""])
    if (args.folder / "quality.md").exists():
        text.extend(["- [Проверка качества по источникам](quality.md)", ""])
    target = args.folder / "comparison.md"
    target.write_text("\n".join(text), encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
