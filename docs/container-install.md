# Установка через Docker Compose (Windows 11 / WSL 2)

Это отдельный CPU-путь поставки существующего приложения. Нативный Windows launcher,
проверенные NPU/GPU backend, CLI и Dev Containers остаются доступны.
Контейнер включает Python, FFmpeg/ffprobe, Tesseract (eng/rus/ukr), OpenCV и faster-whisper.
Модели и Ollama в образ не включены. Поддерживаемая архитектура образа — Linux amd64.

## Чистая Windows

1. Установите [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)
   с [WSL 2 backend](https://docs.docker.com/desktop/features/wsl/). Выполните предложенную
   установщиком перезагрузку, запустите Desktop и дождитесь готовности Linux Engine.
   Если WSL отсутствует, следуйте [официальной инструкции](https://learn.microsoft.com/windows/wsl/install).
   Наш скрипт не устанавливает Docker, не включает компоненты Windows и не меняет драйверы.
2. Скачайте исходники репозитория как ZIP (Code → Download ZIP) или клонируйте его.
   Распакуйте в постоянную доступную для записи папку. Для первого запуска из исходников
   требуется интернет для сборки образа. Python и Git устанавливать не нужно.
   После первого настоящего релиза используйте `VideoDescriptor-vX.Y.Z-compose.zip` из Releases:
   такой комплект скачивает готовый версионированный образ GHCR вместо сборки.
3. Откройте PowerShell в распакованной папке:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\VideoDescriptor.ps1 -Action Install
   ```

4. Откройте **http://localhost:8000/create**. Для речи выберите **Whisper small · CPU**.
   Первый запуск распознавания скачает small multilingual из Hugging Face (порядка 0.5 ГБ;
   актуальный размер зависит от версии модели). Нужен доступ к сети и свободное место
   также для видео, WAV и промежуточных результатов. Для одного текста отключите
   конспект/перевод и анализ изображения: Ollama и API-ключ не нужны.
   Установка сама не скачивает модели; запуск распознавания инициирует загрузку.

Скрипт проверяет Docker CLI, Compose v2, Engine/Linux, наличие WSL 2 дистрибутива
и WSL-ядро активного Engine; создаёт `.env` и каталоги, выполняет Compose `--wait`
и HTTP readiness. Системные prerequisites пользователь устанавливает сам.

## Управление и обновление

```powershell
.\scripts\VideoDescriptor.ps1 -Action Start
.\scripts\VideoDescriptor.ps1 -Action Stop
.\scripts\VideoDescriptor.ps1 -Action Status
.\scripts\VideoDescriptor.ps1 -Action Logs
# Обновление из исходников: сначала заменить исходники новой версией, затем:
.\scripts\VideoDescriptor.ps1 -Action Update
# Обновление опубликованного образа: указать существующую проверенную версию:
.\scripts\VideoDescriptor.ps1 -Action Update -Image ghcr.io/iavnfgv/video-descriptor:vX.Y.Z
.\scripts\VideoDescriptor.ps1 -Action Uninstall
```

Образ GHCR появится только после настоящего релиза. Пример `vX.Y.Z` — placeholder,
не существующий опубликованный тег. Не заменяйте рабочую версию непроверенным `latest`.
При обновлении готовым ZIP распакуйте его поверх прежней папки и запустите Install:
VERSION выберет новый образ, `.env` и данные сохранятся. Не запускайте его из новой
случайной папки: относительный путь данных укажет на другое рабочее пространство.
Перед обновлением дождитесь конца задач или остановите их; незавершённая работа
после перезапуска станет ошибкой с сохранёнными checkpoint. Повторите её через UI.
Задания, оставленные в `queued`, после старта продолжают выполняться.

Uninstall удаляет контейнер и сеть, **сохраняет** данные, настройки и кэш.
Для полного удаления после резервного копирования вручную удалите выделенную папку
данных и распакованные файлы приложения; ненужный образ удаляется `docker image rm IMAGE`.
Скрипт не удаляет Docker Desktop или другие приложения.

## Постоянные данные и секреты

По умолчанию рядом с Compose создаётся `container-data/`, подключённая к `/workspace`:

| Каталог внутри неё | Содержимое |
| --- | --- |
| `data/uploads` | Исходные загруженные записи |
| `output` | Результаты, checkpoints, версии, файловая очередь `jobs`, журналы |
| `.devcontainer` | Настройки перевода/API-ключ, промпты и настройки конструктора |
| `cache/huggingface` | Скачанные модели faster-whisper |

Для резервной копии остановите приложение и скопируйте **всю** эту папку вместе с `.env`.
Местоположение меняется через `VIDEO_DESCRIPTOR_HOME` в `.env`. Для Linux каталог
должен быть доступен UID 1000 на запись (например, `sudo chown -R 1000:1000 ./container-data`
только для выделенной новой папки). Windows Docker Desktop обрабатывает bind mount иначе.
Старые очереди/результаты из Dev Container и native workspace автоматически не импортируются:
они содержат абсолютные пути. Простое подключение прежнего корня небезопасно.

`.env` не копируется в образ и игнорируется Git. Ключ Gemini лучше вводить в «Подключениях»;
он сохраняется в приватной `.devcontainer/translation-settings.json`, закрытой для HTTP.
Допускается `GEMINI_API_KEY` в локальной `.env`; окружение контейнера видно владельцу Docker.
Не публикуйте `docker compose config`, inspect и архив настроек: они могут содержать ключ.
Интерфейс без аутентификации: порт по умолчанию опубликован только на **127.0.0.1:8000**.

## Ollama и Gemini

Для локальных конспектов и перевода запустите Ollama на Windows и установите нужную модель.
В `.env` задайте `OLLAMA_BASE_URL=http://host.docker.internal:11434` и `OLLAMA_MODEL`;
модель перевода также выбирается в «Подключениях» UI. Конструктор позволяет выбрать Gemini
отдельно: облачные речь/конспект/перевод используют сохранённый ключ и отправляют данные Google.
Ollama не требуется для CPU-транскрипции или выбранных Gemini-стадий.
Исторический общий lecture pipeline без настроенного конструктора использует Ollama;
это не полностью облачный режим. Выбирайте провайдера для каждой нужной стадии.

Откройте [диагностику подключений](http://localhost:8000/api/diagnostics): она различает
недоступную Ollama, отсутствующую выбранную модель, отсутствие ключа и HTTP-отказ Gemini.
Она делает только запросы списка моделей, не скачивает веса и не вызывает генерацию.
Успешный список Gemini не гарантирует квоту конкретной генерации. HTTP `/health`
проверяет готовность самого HTTP-сервера и не зависит от необязательных провайдеров.
Supervisor контролирует жизнь worker; Docker healthcheck сам по себе не перезапускает
«unhealthy» контейнер, restart policy применяется при завершении процесса.

## CPU, Intel GPU/NPU и ограничения

- Базовый образ: faster-whisper small CPU int8, без диаризации. Torch/pyannote,
  Intel XPU runtime, OpenVINO и модели не устанавливаются.
- NPU остаётся Windows HTTP-сервисом. `SPEECH_NPU_URL` по умолчанию указывает на
  `host.docker.internal:8766`. Сервис должен быть доступен из контейнера, иметь проверенный
  профиль small/multilingual/static/beam=1 и отключённый word_timestamps.
  Loopback-only сервис может быть недоступен через host gateway; не меняйте его bind/firewall
  автоматически. Протокол и существующий native путь сохранены; аппаратный контейнерный
  сценарий этим изменением не проверен.
- Не обещаем прямой Intel GPU/NPU passthrough в Docker Desktop. Существующий Intel Dev
  Container и native Auto NPU → GPU → CPU остаются отдельными путями с прежними проверками.
- Диаризация (`pyannote`, Torch, токен и принятые условия моделей) требует отдельного
  окружения; XPU — подготовленного Intel runtime. Эти варианты видны в общем UI, но не
  входят в базовый CPU-образ. Выбирайте Whisper CPU без голосов либо Gemini.
- Обновление образа не означает побитовую воспроизводимость его пересборки: Python runtime
  зависимости закреплены Linux wheel hashes, базовый Python-образ закреплён digest,
  но apt получает обновления. Для точного развёртывания используйте digest опубликованного образа
  через Compose; PowerShell оболочка принимает версионированные теги.

## Типичные ошибки

- Docker отсутствует / Engine недоступен: установите или запустите Desktop; проверьте
  Linux containers и WSL 2 backend. Скрипт печатает инструкции и прекращает запуск.
- Desktop падает до Engine: смотрите `%LOCALAPPDATA%\Docker\log\host` и официальную
  [диагностику Docker](https://docs.docker.com/desktop/troubleshoot-and-support/troubleshoot/).
  Это отдельная неисправность Docker, не успешная сборка приложения.
- Порт 8000 занят: остановите конфликтующее приложение сами или задайте
  `VIDEO_DESCRIPTOR_PORT=8001` в `.env`; скрипт напечатает соответствующий адрес.
- Ollama недоступна: проверьте адрес, доступ через host gateway и firewall; существующий
  рабочий сервис автоматически не перенастраивается. В Linux добавлен host-gateway alias.
- Gemini HTTP 400/401/403: проверьте ключ и разрешения проекта; 429 — квота/ограничение.
- GHCR denied/not found: проверьте опубликованный тег и публичность пакета; приватный
  пакет потребует `docker login ghcr.io`, контейнер не должен хранить токен реестра.
- Не загружается Whisper: проверьте интернет/Hugging Face, свободное место и права кэша.
  Скачанные модели переживают пересоздание; без готовой модели офлайн-ASR не обещается.

## CI и настоящий релиз

`container-ci.yml`: push/PR, Linux Python dependencies, pytest, Ruff, pip check,
Compose config, Docker build и реальные lifecycle smoke без моделей/Ollama/GPU.
Smoke проверяет HTTP/UI, обработку невалидного файла через очередь, восстановление
прерванного задания, idle worker, сохранность данных/настроек/кэша после stop/recreate
и автоматический рестарт после аварии worker. Это не проверка качества ASR.

`container-release.yml`: настоящий `vX.Y.Z` → те же проверки → GHCR version/SHA tags →
smoke опубликованного образа → ZIP Compose/PowerShell/VERSION и SHA256 → GitHub Release.
Ручной workflow_dispatch без тега выполняет только verify, ничего не публикует.
Существующий `windows-release.yml` сохранён для native ZIP/installer lifecycle.
Приватный GHCR-пакет проверяется runner с авторизацией до logout; повтор прерванного
выпуска может использовать уже опубликованный образ того же commit, но откажется
перезаписать версию другого commit.

Администратору репозитория: разрешить Actions и `packages:write`/`contents:write`,
проверить правила тегов и сделать GHCR package публичным для установки без login.
При ранее созданном package привязать репозиторий и разрешить Actions доступ.
См. [GHCR permissions](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
и [официальный workflow публикации](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images).
Не создавайте первый релизный тег до успешного CI и реального smoke контейнера.

Фактические проверки этого изменения фиксируются в `docs/container-verification.md`;
наличие workflow не считается его успешным выполнением на GitHub.
