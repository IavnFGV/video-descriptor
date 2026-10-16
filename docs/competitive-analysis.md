# Сравнение и продуктовая позиция

Проверено 16 октября 2026 по README, исходникам, конфигурации запуска и лицензиям.
Ревизии и даты последних коммитов зафиксированы в [upstream-snapshot.json](research/upstream-snapshot.json).
Это анализ репозиториев, а не сравнительный запуск на одном наборе видео.
«Не подтверждено» означает отсутствие достаточного подтверждения в просмотренных материалах.

## Кому нужен наш проект

Первый пользователь — человек с Windows Intel AI PC, которому нужно превратить
семейную запись, интервью или лекцию в проверяемый текст, перевод и конспект.
Пользователь открывает приложение ярлыком, добавляет файл, видит этапы, исправляет
результат и забирает субтитры. Он не должен разбираться в Docker, терминалах и GPU-профилях.

Сама транскрибация, локальность, перевод и поддержка Intel GPU **не являются уникальными**.
Vibe уже сочетает desktop, Vulkan, диаризацию и Ollama; Buzz имеет desktop и Vulkan;
Subtitle Edit значительно сильнее в профессиональной правке. Создавать ещё одну
обёртку над Whisper без ясного сценария недостаточно.

Наше проверенное техническое основание — Whisper small FP16 на Intel NPU:
на одном 900-секундном русском WAV получено 41–46 секунд после загрузки модели.
Это результат прошлой диагностики, не скорость всей цепочки и не победа над конкурентами.
Качество, энергопотребление и конкурентную скорость надо измерять отдельно.

## Сравнение

| Проект | Установка Windows и локальная работа | Ускорение, голоса | Перевод, правка и экспорт | Вывод для нас |
|---|---|---|---|---|
| [SubWeaver](https://github.com/rongtianjie/SubWeaver#quick-start) | Поддерживается Compose; React + FastAPI + PostgreSQL, дополнительные worker/мониторинг. Локальные файлы и URL. | [Runner](https://github.com/rongtianjie/SubWeaver/blob/main/backend/app/worker/whisper_runner.py) использует OpenAI Whisper; Intel NPU и диаризация не подтверждены. | LLM API-перевод, bilingual SRT/VTT, TXT; админка, SSE и управление моделями. Точная ручная правка таймингов не подтверждена. | Заимствовать проверку готовности и понятное управление моделями; для одного домашнего пользователя не нужны PostgreSQL, аккаунты и Grafana. |
| [fdff87554/whisper-ui](https://github.com/fdff87554/whisper-ui#architecture) | Docker, FastAPI/htmx/Alpine + Redis/RQ; UI на традиционном китайском. Не найден Windows-инсталлятор. | Faster-Whisper, pyannote 3.1; [выбор устройств](https://github.com/fdff87554/whisper-ui/blob/main/src/whisper_ui/core/device.py): CUDA/ROCm/CPU, не NPU. | Ollama-коррекция текста; это не подтверждение полноценного перевода. SRT/VTT/TXT/JSON/DOCX, batch ZIP. Ручная правка не подтверждена. | Заимствовать разделение лёгкого UI и тяжёлого worker, пакетный экспорт и явные профили оборудования. |
| [docker-talkies](https://github.com/psyb0t/docker-talkies) | API в Docker, локальный каталог моделей, HTTP/WebSocket/MCP; не конечный редактор для семьи. | CPU/CUDA и несколько ASR/TTS-движков. [Stereo diarization](https://github.com/psyb0t/docker-talkies/blob/main/docs/api.md) — каналы L/R, не разделение людей в моно-записи. Intel NPU не подтверждён. | OpenAI-совместимый STT, SRT/VTT; нет подтверждённого редактора субтитров/общего LLM-перевода. | Заимствовать документированный контракт движка и контроль жизненного цикла моделей. Не путать каналы со speaker diarization. |
| [Vidistiller](https://github.com/artificemachine/vidistiller#architecture-diagram) | Локальная web-платформа; в основном Compose: API, UI, PostgreSQL, Redis, worker и админка БД. | В просмотренном [transcript service](https://github.com/artificemachine/vidistiller/blob/main/backend/app/services/transcript.py) строки speaker заполняются `None`; NPU/диаризация не подтверждены. | Видео/URL → документация и текст, OCR; точные subtitle-editing/export возможности надо проверять отдельно. | Близок к нашему сценарию конспектов. Заимствовать ясную схему модулей и тесты сервисов; отличаться доказуемыми ссылками конспекта на фрагмент видео. |
| [self-hosted-video-starter-kit](https://github.com/jaypetersdotdev/self-hosted-video-starter-kit) | Compose + n8n + Postgres + Whisper API; набор для разработчика автоматизаций. | [Код](https://github.com/jaypetersdotdev/self-hosted-video-starter-kit/blob/main/whisper/app/main.py) загружает Whisper base; GPU секция Compose закомментирована, NPU не подтверждён. | JSON-транскрипция/таймкоды и FFmpeg API; бытовой редактор, LLM-перевод и SRT/VTT UI не подтверждены. | Полезны простые workflow-примеры. Нам нужен законченный пользовательский сценарий с меньшим числом обязательных сервисов. |
| [Buzz](https://github.com/chidiwilliams/buzz#features) | Windows desktop-инсталлятор, офлайн-режим, микрофон, файлы, watch-folder. | CUDA, Apple Silicon, Whisper.cpp Vulkan, speaker identification. Intel NPU не подтверждён; заявлять, что Intel ускорение есть только у нас, нельзя. | Whisper-перевод, просмотр/поиск/воспроизведение, плагины конспектов; TXT/SRT/VTT. Полнота произвольного перевода зависит от движка/плагина. | Ориентир для простоты установки, горячих клавиш, очереди и управления загрузками. |
| [Subtitle Edit](https://github.com/SubtitleEdit/subtitleedit/blob/main/docs/overview.md) | Зрелый desktop; Windows-сборки с runtime, дополнительные движки/модели скачиваются отдельно. | [Много движков](https://github.com/SubtitleEdit/subtitleedit/blob/main/docs/features/speech-to-text.md), включая Vulkan/DirectX и диаризацию через отдельные backend. Наш NPU-профиль не подтверждён. | [Перевод](https://github.com/SubtitleEdit/subtitleedit/blob/main/docs/features/auto-translate.md), waveform, полноценные тайминги, масса форматов. | Не конкурировать числом функций редактора. Делать проще первичный проход и передавать SRT/VTT в Subtitle Edit для профессиональной доводки. |
| [Vibe](https://github.com/thewh1teagle/vibe#features) | Desktop Windows/macOS/Linux, офлайн, пакетная обработка. | Vulkan/CoreML, NVIDIA/AMD/Intel, диаризация. [Tauri-команда](https://github.com/thewh1teagle/vibe/blob/main/desktop/src-tauri/src/cmd/transcribe.rs) и редактор просмотрены; NPU не подтверждён. | Перевод Whisper в английский, Ollama-анализ, [редактор](https://github.com/thewh1teagle/vibe/blob/main/desktop/src/pages/main/components/transcript-view.tsx), SRT/VTT/TXT и другие форматы. | Самый близкий ориентир для бытового desktop. Наш шанс — связать речь, перевод и конспект с источниками и восстановлением, затем доказать пользу NPU. |
| [Whisper-WebUI](https://github.com/jhj0517/Whisper-WebUI#installation-and-running) | Gradio; Windows через локальные скрипты/Pinokio либо Docker, адрес 7860. | Silero VAD, UVR, pyannote; [requirements](https://github.com/jhj0517/Whisper-WebUI/blob/master/requirements.txt) содержит указания XPU, но это не доказательство Whisper/NPU или всех операций pyannote на XPU. | Whisper→English, NLLB/DeepL, SRT/VTT/TXT. Полный timeline-редактор не подтверждён. | Заимствовать VAD до распознавания, отдельные stages и явный выбор языка; избежать десятков непонятных параметров на первом экране. |

GitLab-адрес docker-talkies и его API возвращали HTTP 503. Проект исследован в
репозитории того же автора на GitHub; идентичность ревизии GitLab не утверждается.

## Активность и лицензии

| Проект | Последний коммит основной ветки, UTC | Лицензия по репозиторию | Ограничение для заимствования |
|---|---|---|---|
| SubWeaver | 2026-06-19 | Badge MIT, отдельный LICENSE не найден, API license=null | Идеи можно изучать; код не переносить до уточнения разрешения. |
| whisper-ui | 2026-10-07 | [MIT](https://github.com/fdff87554/whisper-ui/blob/main/LICENSE) | При копировании сохранять уведомления; модели имеют свои условия. |
| docker-talkies | 2026-08-27 | [WTFPL v2](https://github.com/psyb0t/docker-talkies/blob/main/LICENSE) | Условия runtime/моделей проверяются отдельно. |
| Vidistiller | 2026-10-08 | [MIT](https://github.com/artificemachine/vidistiller/blob/main/LICENSE) | Сохранять уведомления. |
| video-starter-kit | 2025-07-28 | README «MIT (or your preferred license)», LICENSE не найден | Недостаточно определённая лицензия; n8n лицензируется отдельно. |
| Buzz | 2026-10-11 | [MIT](https://github.com/chidiwilliams/buzz/blob/main/LICENSE) | Учитывать лицензии backend и моделей. |
| Subtitle Edit | 2026-10-16 | [MIT](https://github.com/SubtitleEdit/subtitleedit/blob/main/LICENSE) | Лицензии подключаемых бинарников/моделей отдельные. |
| Vibe | 2026-10-06 | [MIT](https://github.com/thewh1teagle/vibe/blob/main/LICENSE) | Сохранять уведомления. |
| Whisper-WebUI | 2025-12-29 | [Apache-2.0](https://github.com/jhj0517/Whisper-WebUI/blob/master/LICENSE) | Сохранять LICENSE/NOTICE при применимости и отмечать изменения. |

Дата последнего коммита — наблюдение, не оценка качества поддержки или стабильности релиза.
Чужой код в прототип не переносится. Для нашего исходного репозитория отдельная
лицензия пока не выбрана: до публичного распространения нужен выбор владельца.

## Чем именно стремимся быть полезнее

| Обещание продукта | Что уже есть в основном проекте | Что ещё надо доказать |
|---|---|---|
| Открыть ярлыком → добавить видео → получить редактируемый результат | web UI, очередь, редактор, версии | Работа чистой Windows-установки и понятные ошибки без помощи разработчика. |
| Локальный NPU для речи, GPU для говорящих, Ollama для перевода | NPU-профиль и независимые стадии, GPU-результаты старого окружения | Windows XPU/pyannote, качество на сменах языка; измерения всей цепочки. |
| После сбоя не терять час обработки | Блоковые checkpoint и отдельные результаты | Контракт восстановления между версиями и после переноса каталога. |
| Конспект можно проверить по источнику | source_ids, OCR, кадры, видео-переходы | Оценка полезности пользователями и тесты неверных/пропущенных ссылок. |
| Сложные фрагменты не превращаются в выдуманные субтитры | VAD, строгая валидация границ | needs_review для `end=-1`, удобный переход к проблемному фрагменту. |

Первый показ: ярлык, один экран добавления, реальный прогресс, воспроизведение,
правка одной ошибки с таймкодом, выгрузка SRT/VTT, прерывание и продолжение с кэша.
В демо явно отделять работающие режимы от экспериментальной диаризации.
До публикации: одинаковый набор EN/RU/UK/тишина/музыка/несколько людей для нас,
Vibe и Buzz; раздельно startup/recognition/diarization/translation/end-to-end,
WER/CER на ручной эталонной разметке, ошибки говорящих и таймингов, потребление памяти.
