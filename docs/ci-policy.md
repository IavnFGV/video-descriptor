# CI: события, проверки и артефакты

Источник поведения — [workflows](../.github/workflows). Локальные команды:
[тестирование](development/testing.md); BUILD, теги и публикация Windows:
[процедура выпуска](development/releases.md).

## Автоматическая маршрутизация

`ci.yml` запускается для PR (opened, synchronize, reopened, ready_for_review)
и push в main. Push feature-ветки без PR не запускает CI. Workflow-level path
filters отсутствуют; `scripts/ci_changes.py` выбирает jobs внутри одного run.

| Изменения | Проверки |
| --- | --- |
| Только Markdown | Configuration/paths: actionlint и policy tests; затем `required` |
| Код | Fast unit suite на Linux и Windows; Ruff/CSS/DOM/API/JS один раз на Linux |
| Windows UI/backend | Дополнительно reusable Windows smoke: ZIP, WebView2, readiness |
| Packaging/runtime dependencies | Windows smoke также собирает/устанавливает installer |
| Docker/Compose и связанные backend paths | Дополнительно reusable container build/smoke |

Точная классификация путей находится в [ci_changes.py](../scripts/ci_changes.py),
не в расширении файла само по себе: например, `opencode.json` включает Fast.
Smoke не скачивает модели и не доказывает ASR или поддержку NPU/GPU.

## Семь workflows

| Файл | Триггер и назначение |
| --- | --- |
| `ci.yml` | PR/main push; маршрутизация, Fast, условные smoke, стабильный `required` |
| `windows-smoke.yml` | Только `workflow_call`; ZIP/WebView2 и условная install/health/uninstall smoke |
| `container-smoke.yml` | Только `workflow_call`; одна сборка Docker и lifecycle/persistence smoke без моделей |
| `full-acceptance.yml` | `workflow_dispatch`, `workflow_call`, release prereleased/published; полная приёмка точных пакетов |
| `windows-release.yml` | Native version/build tags и ручной запуск; подготовка на main либо проверка и публикация тега |
| `container-release.yml` | Только `workflow_dispatch`; Full Acceptance, затем публикация лишь на `vX.Y.Z` |
| `model-behavior.yml` | Только `workflow_dispatch`; отдельная реальная модель и corpus, не релизный gate |

Container release не реагирует автоматически на version tags и не принимает
`vX.Y.Z-build.N` для публикации. Ручной запуск на ветке выполняет verify, но
пропускает publish. На semantic tag публикуются принятый образ GHCR, Compose ZIP
и принятые Windows artifacts без пересборки. Этот старый комбинированный publisher
не дополняет существующий native Release: он вызывает `gh release create`.
Не запускайте его на теге уже опубликованного Windows-релиза.

## Full Acceptance и доказательства

Full проверяет воспроизводимость ZIP, WebView2, полный installer lifecycle и
установленный API/UI путь с настоящим CPU Whisper. LLM HTTP boundary заменяется
disposable fixture (`--llm-fixture`): Ollama runtime и LLM-веса не скачиваются.
Проверяются translation/notes/article, редакторы, экспорт, неверный ответ и
сохранность исходника, но не качество генерации реальной модели.

Windows release вызывает Full с `windows_only=true`; контейнерная job пропускается.
Ручной Full и container release по умолчанию включают контейнерную приёмку.
Release-event скачивает точные uploaded ZIP/EXE/checksums/provenance, проверяет
revision/hashes и тестирует эти файлы без fallback на rebuild. Старые assets без
provenance не считаются принятыми. Событие от публикации через `GITHUB_TOKEN`
не порождает рекурсивный workflow; native publisher уже прошёл Full до публикации.

[Model behavior](model-behavior.md) отдельно проверяет настоящую LLM.
[Sandbox](windows-sandbox.md) запускается явно для проверки окружения;
runner, mock и Sandbox не доказывают работу конкретного NPU/GPU.

## Concurrency, права и кэши

CI group различает workflow/event и PR number либо main SHA. Новый commit отменяет
предыдущий run только своего PR. Full/container release используют отдельные run
groups без отмены; Windows release сериализует одинаковый ref без отмены.

Рекомендуемый обязательный check — **required** из CI: он требует success от
configuration и допускает только success/skipped зависимых jobs. Настройки branch
protection/rulesets находятся вне YAML и здесь не считаются проверенными.

PR jobs имеют `contents:read`; write permissions ограничены подготовкой/публикацией.
Actions закреплены commit SHA. Python CI — 3.12, Node закреплён в YAML;
embedded Python пакета закреплён отдельно в `release-inputs.json`.

- pip cache зависит от ОС и lockfiles; модели и пользовательский workspace туда не входят.
- Build inputs/wheels проверяются закреплёнными SHA256, Inno также подписью издателя.
- actionlint скачивается через `download_build_file.py`, кэш проверяется по SHA256.
  Сетевые повторы не ослабляют hash/signature checks.
- Container smoke использует BuildKit cache и `--no-build` smoke после одной сборки.
- Full Whisper fixture сверяет revision/hash при cache hit; это не LLM download.

Smoke сохраняет JSON-отчёты 5 дней. Full сохраняет принятые Windows artifacts
и отчёты 14 дней, принятый container image 7 дней; при ошибке — отчёты 7 дней.
Fast не публикует установщики.

## Публичная граница

`ci_artifacts.py` проверяет стандартный профиль, отсутствие весов/component cache,
реальный состав ZIP и соответствие manifest/provenance. Publisher повторяет gate
перед upload. Domestic/cached builders удалены; старые proof не разрешают такую
публикацию. Технический gate не заменяет
[проверку лицензий](../windows-app/THIRD-PARTY.md).

Локальный post-merge build не является CI job и не публикует Release:
[настройка и побочные эффекты](local-build.md). Старые замеры CI и изменения
маршрутизации сохранены в [истории разработки](development/history.md) и
[отчёте Compose](container-verification.md); это не текущие триггеры.
