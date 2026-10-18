# Проверка Compose-поставки — 18.10.2026

Исходный HEAD: 9ee8f59, main. Проверка выполнена на Windows 11 и в отдельном
CPU Python-окружении Ubuntu WSL 2; старый WSL-репозиторий и native NPU-сервисы не менялись.

## Реально выполнено

- Исходный pytest в Windows без UTF-8: 19 failed, 191 passed, 1 skipped. Причина —
  чтение UTF-8 файлов через системную cp1252. Повтор с `python -X utf8 -m pytest -q`:
  **210 passed, 1 skipped**. Существующий Windows CI уже задаёт PYTHONUTF8=1.
- После изменений, включая исправление Windows path alias: **219 passed, 2 skipped**. Пропуски: существующее отсутствие
  права symlink и новый Linux-only тест supervisor/process groups.
- Linux Ubuntu WSL, CPython 3.12.3: **221 passed**. Полный набор тестов, включая
  настоящий запуск supervisor/HTTP/worker, SIGTERM → exit 0, SIGKILL worker → exit 1,
  повторный запуск и состояние interrupted → error с сохранением файлов.
- `pip install --require-hashes -r requirements-container.lock` в отдельном Linux venv:
  успешно. Все runtime зависимости установлены с Linux wheel SHA256, без весов моделей.
- Ruff проверен на Windows и Linux для video_descriptor, tests, windows-app,
  scripts/smoke_compose.py и scripts/whisper_npu_server.py; ошибок нет.
- `pip check` в Windows и новом Linux venv: ошибок нет.
- `docker compose config --quiet`: успешно, без вывода resolved config/секретов.
- PowerShell AST parse: успешно; настоящий запуск через Windows PowerShell 5.1 при
  выключенном Engine завершается ошибкой и инструкцией запуска Docker, до создания .env/данных.
- YAML workflows разбирается; `python -m video_descriptor --help` работает.

## Проверка на GitHub Actions

[Container CI для db50437](https://github.com/IavnFGV/video-descriptor/actions/runs/39149394797)
**успешен**: установка hash-locked зависимостей, pytest/Ruff, Compose validation,
Docker build и настоящий lifecycle smoke на Ubuntu runner. Smoke подтвердил HTTP/UI,
очередь/ошибку невалидного медиа, idle worker, interrupted → error, сохранность
входа/результата/настроек/кэша после stop/recreate и restart после аварии worker.
Это проверка без ML-моделей, не подтверждение качества ASR.

Первый [Windows workflow](https://github.com/IavnFGV/video-descriptor/actions/runs/39149394771)
прошёл unit/Ruff, сборку ZIP/installer и побайтную воспроизводимость ZIP,
но остановился в lifecycle: runner использует RUNNER~1 в TEMP, а приложение возвращает
полный resolved путь. verify_release сравнивал написание пути вместо идентичности
каталога. Проверка заменена на samefile: проверяются тот же каталог и отказ для чужого
каталога; добавлена регрессия.

Повтор для **dca7d9a**: [Container CI](https://github.com/IavnFGV/video-descriptor/actions/runs/39149814516)
и [Windows lifecycle](https://github.com/IavnFGV/video-descriptor/actions/runs/39149814507)
оба **success**. Windows runner: 220 passed, 1 skipped; 4391 файлов ZIP проверено,
ZIP повторно побайтно совпал (SHA256 `64686689177103c18212b4348ab683578c43484d28be551812d981126ff9e8bf`).
Запуск ZIP и установленной копии без системного Python, graceful stop, install/reinstall,
отказ обновления работающей установки, upgrade fixture и uninstall с сохранением
настроек/данных подтверждены. Артефакт VideoDescriptor-windows-x64-preview загружен.
Это Windows Server 2025 hosted runner без моделей, а не приёмка ASR на чистой Windows 11.

После этих прогонов изменены только release workflow и документация: GHCR login
сохраняется до проверки опубликованного (в том числе приватного) образа, logout — always;
повтор после прерывания переиспользует версию лишь с тем же revision label.
YAML и bash-сценарии release workflow проверены синтаксически через bash -n.
Публикация остаётся непроверенной: настоящий tag/registry release здесь не запускались.

## Повторная локальная проверка после обновления Docker

После обновления пользователем: Docker Desktop **4.95.0 (242831)**, Engine **29.8.2**,
Compose **5.6.0**, Linux amd64, ядро `6.6.87.2-microsoft-standard-WSL2`.
Проверена рабочая копия b5701b6 на этой Windows-машине:

- `docker compose config --quiet` и настоящая локальная `docker compose build` — успешно.
- `python -X utf8 scripts/smoke_compose.py` — **PASS**: HTTP/UI, обработка очереди и
  ошибки невалидного медиа, idle worker, interrupted job, сохранность данных/настроек/
  кэша после stop/recreate и автоматический restart после аварии worker.
  Прогон использовал отдельную временную папку и проект; временный контейнер удалён.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/VideoDescriptor.ps1 -Action Install`
  — успешно: WSL/Engine preflight, создание локальной конфигурации и каталогов,
  сборка, Compose readiness, HTTP readiness. Создана новая `container-data`, старая очередь
  и native-сервисы не подключались и не изменялись.
- После установки `/health` возвращает `ok`, `/create` — HTTP 200;
  `video-descriptor-app-1` healthy, опубликован только `127.0.0.1:8000`.
  Приложение оставлено запущенным для пользователя.
- Отдельный дополнительный Stop/Start через PowerShell launcher не выполнялся:
  составную команду отклонил автоматический контроль выполнения (`blocked by policy`).
  Это не сбой Docker; stop/recreate/restart реально проверены smoke-сценарием выше.

Docker Desktop отдельно сообщил о сбое **Ubuntu WSL integration**: в Ubuntu не найден
`/mnt/wsl/docker-desktop/shared-sockets/host-services/backend.sock` и `/var/run/docker.sock`.
При этом Engine в distro docker-desktop продолжал обслуживать Windows CLI и приложение.
Предложен Restart the WSL integration в диалоге; повторное появление ошибки можно
обойти Skip WSL distro integration для Windows/PowerShell пути. Это не подтверждает
исправность Docker CLI внутри Ubuntu. Настройки интеграции автоматически не менялись.
Разделение Engine и необязательной интеграции дистрибутива описано в
[документации Docker](https://docs.docker.com/desktop/features/wsl/).

Модели не скачивались. Реальный ML inference и GPU/NPU внутри контейнера,
приёмка чистой Windows и публикация GHCR по-прежнему не проверялись этим прогоном.

## Первоначальная локальная ошибка (устранена обновлением Docker)

Docker Desktop 4.67.0 установлен, Ubuntu и docker-desktop зарегистрированы как WSL 2.
Engine недоступен. Попытка `docker desktop start` закончилась внутренней ошибкой Desktop:
`initializing Inference manager ... dockerInference: The file cannot be accessed by the system`.
Журнал: `%LOCALAPPDATA%\Docker\log\host\com.docker.backend.exe.log`.
Речь о runtime reparse point; безопасное переименование этого объекта также отклонено
Windows. Runtime-файл и настройки Docker не изменились, factory reset и переустановка не выполнялись.

Поэтому **Docker build попытались выполнить, но он не начался из-за отсутствия Engine**.
Контейнерный smoke `scripts/smoke_compose.py`, bind mount persistence при реальном
stop/recreate и container restart policy локально **не выполнены**.
Linux Python-тесты не считаются заменой Docker-проверки.
Они включены как обязательные шаги container-ci и перед публикацией релиза.

GHCR image/Release/релизный тег не создавались. Публичность GHCR package и права
Actions требуют проверки владельцем репозитория при первом настоящем выпуске.
Чистая Windows установка с рабочим Docker Engine, ML inference в контейнере,
NPU/GPU из контейнера и обновление между двумя опубликованными версиями не проверены.

## Команды повторения и следующий этап

Сборка и smoke ниже уже успешно повторены после обновления Docker. Из корня репозитория:

```powershell
docker compose config --quiet
docker compose build
python scripts/smoke_compose.py
```

Для smoke достаточно Python 3.11+ standard library на машине разработчика.
Пользовательский установщик Python на хосте не требует.
После успешного CI проверить установку готового Compose ZIP на чистой Windows 11,
короткий реальный CPU ASR, остановку/обновление/удаление с сохранением данных.
Только затем создавать настоящий version tag и принимать GHCR release chain.
