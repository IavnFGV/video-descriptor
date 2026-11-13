# Video Descriptor — Windows Desktop

Нативное WinForms/WebView2-приложение с локальным Python backend. Для установленного
пакета не нужны Docker, WSL, системный Python или отдельная установка OpenVINO.
Модели Whisper и community-1 в стандартный пакет не входят.

## Установка и запуск

Скачайте стандартный установщик или ZIP из
[Releases](https://github.com/IavnFGV/video-descriptor/releases).
Установщик работает для текущего пользователя и создаёт пункт Start Menu;
ярлык на рабочем столе необязателен. Если WebView2 отсутствует, установщик
подготавливает закреплённый app-local Runtime; для ZIP Runtime нужен отдельно.
Подробности: [состав пакета](../docs/windows-release.md).

Из Start Menu откройте **Video Descriptor**, из ZIP — **Open Video Descriptor.cmd**.
В настройках AI подключите или с явным согласием скачайте проверенную Whisper small
FP16, выберите устройство и подготовьте распознавание. Для диаризации отдельно
подготовьте pyannote/community-1. См. [настройку AI](../docs/ai-setup-windows.md)
и [менеджер компонентов](../docs/ai-component-manager.md).

Добавьте видео/аудио, запустите распознавание, проверьте текст и экспортируйте
SRT/VTT/TXT. Перевод, конспект и статья используют отдельно настроенный
[Ollama](../docs/ollama-windows.md), [LM Studio](../docs/lmstudio-windows.md)
или [Gemini](../docs/translation-providers.md). Ollama и LM Studio — внешние
серверы: приложение не устанавливает и не запускает их, не скачивает их модели.

Крестик скрывает окно в трей; обработка продолжается. Для полного выхода используйте
**Завершить приложение** в трее. При активной очереди остановка отклоняется.
Внешние серверы Ollama/NPU не останавливаются. См. [desktop host](../docs/desktop-windows.md).

## Работа из исходников

Из корня репозитория, при установленном Python 3.11+ и WebView2:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows-app\Install-App.ps1 -CreateShortcut
.\windows-app\Start-App.ps1 -Doctor
.\windows-app\Start-App.ps1
```

`Install-App.ps1` создаёт `.venv-windows`, устанавливает
`windows-app/requirements-lock.txt` и подготавливает desktop host/SDK.
Он скачивает зависимости, но не модели и драйверы; существующая `.venv-npu`
не используется как окружение приложения. `-CreateShortcut` необязателен.

Поддерживаемые режимы launcher:

```powershell
.\windows-app\Start-App.ps1 -NoBrowser
.\windows-app\Start-App.ps1 -StartNpu
.\windows-app\Start-App.ps1 -Stop
```

`-StartNpu` явно подготавливает NPU worker; `-Stop` сохраняет защиту активной
очереди. Для отдельного source preview и локальных проверок см.
[руководство разработки](../docs/development/README.md) и
[тестирование](../docs/development/testing.md): Windows Fast использует `.venv`,
а не автоматически созданную launcher-среду `.venv-windows`.

## Конфигурация и данные

Значения по умолчанию находятся в [config.example.json](config.example.json).
`windows-app/config.local.json` переопределяет их; Python backend также поддерживает
`VIDEO_DESCRIPTOR_CONFIG` для другого файла настроек. Обычные пользовательские
подключения и пути меняйте через UI, а не редактированием JSON работающего backend.

| Параметр | Назначение |
| --- | --- |
| `port` | Loopback HTTP, по умолчанию 8780 |
| `records_directory` | Выбранное хранилище записей; при отсутствии используется `workspace` |
| `workspace` | По умолчанию `runtime/workspace`; этот относительный путь ограничен `windows-app/runtime` |
| `npu_url`, `cpu_url`, `gpu_url` | Loopback speech workers, по умолчанию 8766 / 8767 / 8768 |
| `whisper_model_directory`, `openvino_python` | Локальная Whisper IR и Python worker; доступность проверяется отдельно |
| `npu_worker_directory` | Каталог существующего внешнего benchmark worker, если используется |
| `diarization_python`, `diarization_model_directory`, `diarization_device` | Отдельная среда, модель и устройство диаризации |
| `ollama_url`, `ollama_model` | Внешний endpoint и явно выбранная модель; по умолчанию модель пуста |
| `application_log_directory` | Общий журнал вне переносимых папок записей |

В хранилище: `data/uploads` — исходники, `output` — результаты и очередь,
`.devcontainer` — настройки стадий/подключений. Общий журнал по умолчанию —
`windows-app/runtime/logs/events.jsonl`. Компоненты AI хранятся отдельно в профиле
пользователя; см. [расположение и восстановление](../docs/ai-component-manager.md#files-recovery-updates).

Перед обновлением сохраните хранилище и локальную конфигурацию. Удаление приложения
не должно удалять записи и внешние модели. Проверка обновлений уведомляет о новом
релизе и открывает его страницу, но не скачивает и не устанавливает пакет.
Исторические WSL-очереди не импортируются автоматически: абсолютные Linux-пути
требуют отдельной миграции.

## Проверки и ограничения

Auto выбирает готовый speech backend NPU → Intel OpenVINO GPU → CPU; явный выбор
не подменяется. Настройка Whisper не переключает устройство pyannote или LLM.
Сохранение checkpoints, исходных ответов и ручных правок описано в
[руководстве восстановления](../docs/development/debugging.md).

[Исторические аппаратные проверки](../docs/verification-devices.md) относятся
к указанным моделям и драйверам, а не ко всем GPU/NPU. Текущая релизная приёмка:
[процедура выпуска](../docs/development/releases.md). Сборка и локальные проверки
не доказывают качество EN/UK/mixed-language или совместимость любой чистой Windows.

[Архитектура](../docs/architecture/README.md) ·
[Компоненты и контрольные суммы](component-manifest.json) · [Лицензии](THIRD-PARTY.md)
