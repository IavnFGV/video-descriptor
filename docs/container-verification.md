# Проверка Compose-поставки — 18.10.2026

Исходный HEAD: 9ee8f59, main. Проверка выполнена на Windows 11 и в отдельном
CPU Python-окружении Ubuntu WSL 2; старый WSL-репозиторий и native NPU-сервисы не менялись.

## Реально выполнено

- Исходный pytest в Windows без UTF-8: 19 failed, 191 passed, 1 skipped. Причина —
  чтение UTF-8 файлов через системную cp1252. Повтор с `python -X utf8 -m pytest -q`:
  **210 passed, 1 skipped**. Существующий Windows CI уже задаёт PYTHONUTF8=1.
- После изменений Windows: **217 passed, 2 skipped**. Пропуски: существующее отсутствие
  права symlink и новый Linux-only тест supervisor/process groups.
- Linux Ubuntu WSL, CPython 3.12.3: **219 passed**. Полный набор тестов, включая
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

## Что не удалось подтвердить

Docker Desktop 4.67.0 установлен, Ubuntu и docker-desktop зарегистрированы как WSL 2.
Engine недоступен. Попытка `docker desktop start` закончилась внутренней ошибкой Desktop:
`initializing Inference manager ... dockerInference: The file cannot be accessed by the system`.
Журнал: `%LOCALAPPDATA%\Docker\log\host\com.docker.backend.exe.log`.
Речь о runtime reparse point; безопасное переименование этого объекта также отклонено
Windows. Файлы/настройки Docker не изменились, factory reset и переустановка не выполнялись.

Поэтому **Docker build попытались выполнить, но он не начался из-за отсутствия Engine**.
Контейнерный smoke `scripts/smoke_compose.py`, bind mount persistence при реальном
stop/recreate и container restart policy локально **не выполнены**.
Linux Python-тесты не считаются заменой Docker-проверки.
Они включены как обязательные шаги container-ci и перед публикацией релиза.

GitHub workflows подготовлены; их успешное исполнение здесь не заявляется.
GHCR image/Release/релизный тег не создавались. Публичность GHCR package и права
Actions требуют проверки владельцем репозитория при первом настоящем выпуске.
Чистая Windows установка с рабочим Docker Engine, ML inference в контейнере,
NPU/GPU из контейнера и обновление между двумя опубликованными версиями не проверены.

## Следующая обязательная проверка

Восстановить Docker Desktop по его диагностике, затем из корня репозитория:

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
