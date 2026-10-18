# Аудит контейнерной поставки — 18.10.2026

Исходная точка — 9ee8f59, чистое дерево main, 12 локальных native-коммитов сверх origin.
Исследованы pyproject, requirements, Dev Containers, serve/jobs/speech, настройки,
Windows launcher, текущие release workflows и инструкции миграции.

| Назначение | Что действительно нужно |
| --- | --- |
| HTTP, файловая очередь, запросы API | Python ≥3.11, pydantic, requests; отдельный web framework/DB не нужны |
| CPU Whisper | faster-whisper → CTranslate2, ONNX Runtime/VAD, tokenizers, Hugging Face, PyAV/numpy; модель small отдельно |
| Медиа | FFmpeg и ffprobe; распаковка WAV/нарезка/кадры |
| Кадры/OCR | OpenCV headless, Tesseract и языковые данные; CPU-речь сама OCR не использует |
| NPU/Intel backend | Windows OpenVINO worker и IR-веса вне CPU-образа; HTTP 8766 с проверкой профиля |
| Диаризация | Torch + pyannote, HF token/условия моделей; необязательное отдельное venv |
| Intel GPU диаризация | отдельный Torch XPU/runtime и проверенное оборудование; отсутствуют в стандартном образе |
| Локальные конспекты/перевод | Ollama и установленная completion-модель на хосте, HTTP 11434 |
| Gemini речь/перевод/конструктор | HTTPS API, ключ, настройки оплаты/Free Tier; Ollama для выбранных Gemini стадий не нужна |

Основной CLI использует Whisper через whisper_http.py для исторического lecture-пути.
CPU speech в web UI — отдельная ветка faster-whisper. Нельзя считать все режимы CLI
полностью автономными после добавления CPU-образа. Общий lecture pipeline без construction
использует Ollama; модель теперь задаётся OLLAMA_MODEL с прежним default.

Пути: uploads в data/uploads/id; очередь output/jobs/id/job.json, run.log в задании;
результаты/версии/checkpoints/журналы запросов в output/run; translation-settings,
model-prompts, construction-settings/presets в .devcontainer. Контейнер задаёт HF_HOME
в постоянном workspace. Исходная .devcontainer и .env* в образ не копируются.

Прежний serve.main запускает ThreadingHTTPServer; enqueue вызывает jobs.start_worker,
отделяющий worker через Popen, дубли исключает file lock. Worker запускает
speech/CLI/construction/translate через subprocess и раньше выходил после 30 секунд idle.
Одного сервиса достаточно: контейнерный supervisor запускает HTTP и постоянный worker,
сохраняет блокировки/очередь, завершает process group вместе с обработчиками.
При аварии основного процесса контейнер завершается с ошибкой; restart policy
поднимает его снова. Поведение запуска вне контейнера сохранено.

Нельзя безопасно перенести без оговорок: абсолютные пути старой очереди, Windows
исполняемые файлы/модели/драйверы, bind loopback-only NPU worker и Intel XPU venv.
Автоматической миграции/подмены устройства нет. Linux amd64 — целевой CPU-формат;
прямой Intel passthrough на Windows не заявляется.

План реализации: минимальный CPU Dockerfile → persistent workspace и supervisor →
PowerShell lifecycle → pytest/Ruff/Compose/build/smoke CI → gated GHCR/release → документация.
Верификация фиксируется отдельно. Native сервисы, исходник WSL и прежние результаты
не изменяются.
