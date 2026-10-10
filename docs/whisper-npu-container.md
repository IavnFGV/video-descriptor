# NPU из devcontainer через Windows-сервис

Текущий Docker работает через WSL2. Прямой доступ Intel NPU к Linux-контейнеру
не поддержан: [запрос WSL #40842](https://github.com/microsoft/WSL/issues/40842)
и [запрос Intel #56](https://github.com/intel/linux-npu-driver/issues/56) открыты.
В нашем контейнере отсутствует `/dev/accel/accel0`. Изменение `--device` или
установка Linux-драйвера внутри контейнера не создаёт отсутствующий доступ.

Используем схему: приложение в контейнере → HTTP → Windows Whisper → Intel NPU.
Запросы отправляют WAV, а не пути файлов контейнера. Результаты и кэш остаются
в проекте. Windows-процесс держит FP16-модель загруженной, обслуживает
распознавание последовательно и использует проверенный `STATIC_PIPELINE=True`.

## Один запуск в Windows

Скачайте [небольшой архив исполнителя](http://localhost:8000/output/whisper-benchmark/windows-npu-worker.zip).
Распакуйте **в существующую папку Windows-бенчмарка**
`C:\Users\ivand\Downloads\windows-benchmark` с `.venv-npu` и
`OpenVINO-whisper-base-en-fp16-ov`. Затем в PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_whisper_npu.ps1
```

Он запускает NPU-процесс в фоне, без установки новых зависимостей и без скачивания
модели. Дождитесь `READY`. Порт — 8765. Логи: `whisper-npu-worker.log` и
`whisper-npu-worker.err.log`, PID: `whisper-npu-worker.pid`. Если Windows спросит
про доступ к сети, соединение контейнера с этим сервисом должно быть разрешено.

## Проверка из контейнера

```bash
python scripts/doctor.py --whisper
```

Нужен ответ `NPU, base.en, static`. Если соединение не проходит, проверьте
логи Windows-процесса и разрешение порта 8765 в Windows Firewall.
Прямой адрес: `http://host.docker.internal:8765/health`.

Для включения backend в `.devcontainer/runtime.env`:

```dotenv
WHISPER_BACKEND=openvino-http
WHISPER_HTTP_URL=http://host.docker.internal:8765
```

Изменение env-файла применяется после пересоздания контейнера. Без пересоздания
переменные можно задать для следующей команды:

```bash
export WHISPER_BACKEND=openvino-http
export WHISPER_HTTP_URL=http://host.docker.internal:8765
python scripts/process_videos.py "data/новое видео.mp4"
```

Веб-сервер/его рабочая очередь тоже должны быть запущены с этими переменными.
Уже запущенные процессы новые переменные автоматически не получат.

## Кэш и ограничения

Исполнитель пока обслуживает только английскую `base.en`. Аудио отправляется
блоками до 300 секунд, после каждого блока атомарно сохраняется контрольная точка.
При обрыве повторится незавершённый блок; завершённые остаются в кэше.
Ключ контрольной точки включает модель, её контрольную сумму и версии движка.
Готовые расшифровки продолжают переиспользоваться — повторный запуск старой лекции
с готовым кэшем не является проверкой использования NPU.

При недоступном сервисе обработка выдаёт понятную ошибку; скрытой подмены на CPU нет.
Вернуть прежний backend: `WHISPER_BACKEND=faster-whisper`.

## Проверка на реальном NPU

2026-10-09 проверено подключение из devcontainer к Windows-сервису на Intel AI Boost
через `host.docker.internal:8765`. Для `sample.wav` длительностью 300 секунд получено
70 сегментов, 790 слов и таймкоды 0.00–299.76 секунды. Текст полностью совпал
с проверенным NPU-результатом из handoff. Отправка аудио и получение результата
заняли около 4–5 секунд при уже загруженной модели; это одиночная проверка,
а не новый сравнительный benchmark. Повторный вызов использовал контрольную точку
без повторного распознавания.

Результат проверки сохранён в `output/whisper-benchmark/container-npu-result.json`.
Контейнер обращается к Windows-сервису; сам Windows-процесс запускается на хосте.
