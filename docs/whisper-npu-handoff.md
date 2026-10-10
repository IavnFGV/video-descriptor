# Handoff: Whisper на Intel NPU (Windows)

Дата проверки: 2026-10-09. Ноутбук: Intel Core Ultra 7 258V, Intel AI Boost NPU
(архитектура 4000), Arc 140V, 32 GB RAM. NPU виден OpenVINO; драйвер сообщает
`NPU_DRIVER_VERSION=1004778`.

## Итог

Рабочий и проверенный путь для Whisper на NPU:

1. Использовать опубликованный совместимый IR `OpenVINO/whisper-base.en-fp16-ov`.
2. Создавать строго `openvino_genai.WhisperPipeline(model, "NPU", STATIC_PIPELINE=True)`.
3. Использовать `num_beams=1`; для English-only `base.en` не передавать явно
   `task` и `language`.

На `sample.wav` (300.0 с, mono PCM16 16 kHz, SHA-256
`51b81d71651c106933d60558bc460500593e7226454139a0b8cf82af2f11e8be`) получено:

| Устройство | Модель и pipeline | Загрузка | Проходы | Медиана тёплых | RTF |
| --- | --- | ---: | --- | ---: | ---: |
| NPU | official FP16, static | 19.76 с | 7.46 / 7.54 / 7.49 с | **7.52 с** | 0.0251 |
| CPU | official FP16, normal/dynamic | 0.65 с | 18.34 / 19.97 / 17.02 с | **18.50 с** | 0.0617 |

Честный speedup тёплых проходов: **18.50 / 7.52 = 2.46x**. Загрузку модели
не включать в скорость длительного распознавания; NPU компилируется заметно дольше.

Качество NPU не оценивалось только по отсутствию исключения:

- все три NPU-прохода побайтно одинаковы;
- 790 слов, 70 сегментов, таймкоды 0.00–299.76 с;
- начало, середина и конец содержательно соответствуют лекции;
- CPU на тех же FP16 модели/аудио/beam=1 стабилен; сходство текста с NPU 96.6%.

## Команды

В рабочей папке Windows:

```powershell
.\.venv-npu\Scripts\python.exe download_official_whisper_ir.py
.\.venv-npu\Scripts\python.exe benchmark_whisper.py sample.wav --backend openvino --device NPU --openvino-pipeline static --beams 1 --model OpenVINO-whisper-base-en-fp16-ov --repeats 3 --output openvino-npu-static-official-fp16-b1.json
.\.venv-npu\Scripts\python.exe benchmark_whisper.py sample.wav --backend openvino --device CPU --openvino-pipeline dynamic --beams 1 --model OpenVINO-whisper-base-en-fp16-ov --repeats 3 --output openvino-cpu-official-fp16-b1.json
```

Или запускатель `benchmark_whisper_npu.ps1`: при готовом `.venv-npu` он не
переустанавливает зависимости, скачивает только официальный IR при его отсутствии,
и запускает CPU/NPU с корректными режимами.

## Что не работает и почему

Исходный локальный `whisper-base-en-ov` (INT8) нельзя использовать на NPU в этой
версии окружения:

1. `STATIC_PIPELINE=True` падает с `Port for tensor name cache_position was not found`.
2. Dynamic `WhisperPipeline` на NPU не сбрасывает состояние: на 300 с повторяет
   фразы и уходит до 329.8 с по таймкодам.
3. В коротких NPU-пробах 20 с первый запрос корректен, а повтор того же pipeline
   уже неверен (`what would be the,` / `or`). CPU с тем же IR стабилен.

Это соответствует открытому багу OpenVINO: https://github.com/openvinotoolkit/openvino/issues/37937

Попытки локально переэкспортировать FP16 из cache `openai/whisper-base.en` с
`optimum-intel==2.2.0` и `transformers==5.5.4` тоже не дали статически совместимый
IR: static pipeline прекращается с `Stateful models without beam_idx input are not supported`.

## Файлы в архиве

- `benchmark_whisper.py` — измерение, JSON с текстом и сегментами; явно выбирает
  `WhisperPipeline` и static/dynamic режим.
- `download_official_whisper_ir.py` — загрузка только официального FP16 IR.
- `benchmark_whisper_npu.ps1` — автоматизированный запуск.
- `openvino-npu-static-official-fp16-b1.json` и `openvino-cpu-official-fp16-b1.json` — валидное сравнение.
- `openvino-npu-static-b1.json`, `openvino-npu-dynamic-b1.json`, `probe-npu-*.json` — доказательства
  несовместимости/ошибки, не использовать для speedup.

Модели, `.venv-npu` и WAV намеренно не включены, чтобы архив оставался маленьким.
