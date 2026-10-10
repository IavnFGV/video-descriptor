# Whisper на Intel NPU: рабочий вариант и замер

Проверено 2026-10-09 на Windows 11, Intel Core Ultra 7 258V, NPU Intel AI Boost
(архитектура 4000), 32 GB RAM, драйвер 32.0.100.4778. Основной проект находится
в devcontainer; NPU-эксперимент запускается непосредственно в Windows.

## Что работает

Используйте готовую FP16-модель `OpenVINO/whisper-base.en-fp16-ov` и **строго**:

```python
openvino_genai.WhisperPipeline(model_path, "NPU", STATIC_PIPELINE=True)
```

При распознавании: `num_beams=1`, `return_timestamps=True`. Английская `base.en`
не допускает явных `task` и `language`. Для CPU используется обычный
`WhisperPipeline` с теми же моделью, аудио и beam=1.

| Вариант | Загрузка | Проходы на 300 сек аудио | Медиана тёплых |
| --- | ---: | --- | ---: |
| NPU, official FP16, static | 19.76 сек | 7.46 / 7.54 / 7.49 сек | **7.52 сек** |
| CPU, official FP16, dynamic | 0.65 сек | 18.34 / 19.97 / 17.02 сек | **18.50 сек** |

Ускорение тёплого распознавания: **2.46x**. NPU загружается дольше; для одного
короткого запроса загрузка может перекрыть выигрыш. Для длительной работы нужно
держать pipeline загруженным. Это измерение Whisper, не скорости всего конспекта.

Все три NPU-текста одинаковы: 790 слов, 70 сегментов, 0.00–299.76 сек.
CPU-тексты также стабильны; сходство строк CPU/NPU по SequenceMatcher — 96.6%.
Это сходство двух автоматических расшифровок, а не точность по ручному эталону.
В переданном Windows-handoff проверено соответствие начала, середины и конца лекции.

Полный отчёт: [whisper-npu-handoff.md](whisper-npu-handoff.md).
Исходные JSON и версии сохранены локально в
`output/whisper-benchmark/handoff-2026-10-09/`; они исключены из Git.

## Запуск в Windows

В текущем контейнере нет `/dev/accel`, поэтому нужен Windows PowerShell.
Установите Python 3.11/3.12 и [драйвер Intel NPU](https://www.intel.com/content/www/us/en/download/794734/intel-npu-driver-windows.html).
Скачайте `http://localhost:8000/output/whisper-benchmark/windows-benchmark.zip`,
распакуйте и откройте PowerShell в папке архива:

```powershell
powershell -ExecutionPolicy Bypass -File .\benchmark_whisper_npu.ps1
```

Запускатель ищет `python`, `python3`, `py` или стандартную установку Python.
Можно передать `-PythonExe "C:\путь\к\python.exe"`. После установки Python
переоткройте PowerShell. Существующие окружение и модель используются повторно.
В новом окружении нужны только OpenVINO GenAI, NumPy и huggingface_hub;
PyTorch, Transformers и Optimum для загрузки готового IR не требуются.
Подготовка и скачивание не включаются в измерение распознавания.

Отдельные команды при готовом окружении:

```powershell
.\.venv-npu\Scripts\python.exe download_official_whisper_ir.py
.\.venv-npu\Scripts\python.exe benchmark_whisper.py sample.wav --backend openvino --device NPU --openvino-pipeline static --beams 1 --model OpenVINO-whisper-base-en-fp16-ov --output openvino-npu-official-fp16-b1.json
.\.venv-npu\Scripts\python.exe benchmark_whisper.py sample.wav --backend openvino --device CPU --openvino-pipeline dynamic --beams 1 --model OpenVINO-whisper-base-en-fp16-ov --output openvino-cpu-official-fp16-b1.json
```

Скрипт сохраняет текст, таймкоды, версии, настройки, время загрузки и каждого прохода.
Первый проход исключается из медианы тёплых. Можно исследовать короткую часть:
`--start-seconds 120 --duration-seconds 20 --repeats 2`.
`source_audio_sha256` относится к исходному WAV; `audio_sha256` — к реально
переданному нормализованному float32 аудио. Их нельзя путать со старым форматом
отчёта, где `audio_sha256` означал SHA-256 файла WAV.

Проверки пустого текста, аномальных повторов и неверных таймкодов останавливают
выдачу явно ошибочного результата как успешного замера. Они не заменяют прослушивание.
Для сравнения устройств параметры, модель и `audio_sha256` должны совпадать.

## Что оказалось несовместимым

Локальный INT8-экспорт `whisper-base-en-ov` в проверенном окружении:

- static: ошибка `Port for tensor name cache_position was not found`;
- dynamic на NPU: начало правильное, затем повторы, неверные таймкоды и перенос
  состояния между запросами;
- локальный FP16-переэкспорт тоже оказался несовместим со static:
  `Stateful models without beam_idx input are not supported`.

Похожие симптомы описаны в [баге OpenVINO #37937](https://github.com/openvinotoolkit/openvino/issues/37937).
Практический обход проверен: официальный FP16 IR + static pipeline.
Ошибочные результаты в 1.5–2 секунды не подтверждают ускорение.

## Другие языки

`base.en` работает только с английским. Есть официальные многоязычные IR
[whisper-base-fp16-ov](https://huggingface.co/OpenVINO/whisper-base-fp16-ov) и
[whisper-small-fp16-ov](https://huggingface.co/OpenVINO/whisper-small-fp16-ov).
Их корректность и скорость на нашем NPU отдельно ещё не проверены.

## Подготовка того же фрагмента в контейнере

```bash
mkdir -p output/whisper-benchmark
ffmpeg -hide_banner -loglevel error -nostdin -i "data/2026-10-05 11-04-45.mp4" -ss 120 -t 300 -vn -ac 1 -ar 16000 -c:a pcm_s16le output/whisper-benchmark/sample.wav
```

SHA-256 WAV: `51b81d71651c106933d60558bc460500593e7226454139a0b8cf82af2f11e8be`.
Более ранний faster-whisper CPU/int8 с VAD и beam=5 дал 217.68 / 240.77 сек
при работающей Qwen. Этот результат получен с другими библиотекой, параметрами
и нагрузкой; он не является чистым сравнением CPU/NPU.

Для основного конвейера добавлен [Windows-сервис распознавания](whisper-npu-container.md).
Бенчмарк остаётся отдельным измерением, а backend `openvino-http` позволяет отправлять
аудио на NPU из контейнера с сохранением контрольных точек в проекте.
