# CI: стоимость, события и релизные артефакты

## Аудит 19.10.2026

Было 3 workflow: container-ci, windows-release, container-release.
Container CI: push любой ветки + pull_request + workflow_call. Для коммита 9dd2e3b
запустились push 39280781235 и PR 39280787277. Windows PR/main каждый раз выполнял
unit/static, две ZIP-сборки, installer lifecycle и Whisper; release добавлял вторую
установку для Ollama. Container release вызывал повторный Container CI перед
публикацией. Concurrency отсутствовал. Windows dev dependencies не кэшировались;
Linux pytest/Ruff устанавливались без pin. Использовались кэши публичных моделей,
но build downloads не кэшировались. Публиковавшийся Windows asset не проверялся:
release пересобирал tag.

Реальное время jobs main 468f5a3: Windows 11:46, Container 2:58. Обновление общего
статуса отставало от логов; `updated_at` не использован как время вычислений.
Предыдущие ошибки UI acceptance: elevated WebView2 не принимал env debug flags,
isolated Python import и гонка async export link. Они исправлены до этой задачи;
продуктовый код здесь не меняется. Некоторые ранние installer failures были
внешними сбоями скачивания/распаковки. Повторные тяжёлые сборки не исправляют YAML.

Branch API: main.protected=false; protection endpoint 404, repository rulesets [].
Настройки защиты не изменены.

## До / после

| Событие | До | После |
|---|---|---|
| Feature push без PR | Container build/smoke | Нет автоматического CI |
| Документация в PR | Полные Windows/Container | Configuration/paths + stable required |
| UI CSS/JS в PR | Installer lifecycle + модели + Docker | Fast Linux/Windows + ZIP/WebView smoke, без installer/моделей/Docker |
| Backend Python | Все тяжёлые проверки | Fast + релевантный Windows и Docker smoke |
| Dockerfile/Compose | Полные Windows/Container | Fast + Docker build/smoke |
| Installer/runtime deps | Полный acceptance | Fast + build + одна install/health/uninstall smoke |
| Merge/main | Полный E2E | Та же маршрутизация для точного merge SHA |
| Manual full | Частичный optional Ollama | Полный lifecycle, reproducibility, CPU/Ollama API/UI |
| Release | Пересборка tag вместо uploaded asset | Проверка точных published ZIP/EXE и provenance |

## Пять workflow, один автоматический run

- `ci.yml`: PR opened/synchronize/reopened/ready_for_review и push только main.
  Always-on configuration/paths, затем unit suite один раз на Linux и один на
  Windows. Статика CSS/DOM/API/Ruff/JS выполняется один раз на Linux. Markdown-only
  выполняет только actionlint и policy tests. Windows/Docker — условные reusable
  jobs внутри того же run; workflow-level path filters отсутствуют.
- `windows-smoke.yml`: только workflow_call из CI. ZIP строится один раз; реальный
  WebView2/tray/reconnect, portable manifest/offline health/setup. Installer создаётся
  и устанавливается один раз только для packaging/dependency changes. Нет моделей,
  повторной ZIP-сборки, reinstall/upgrade fixture, upload больших бинарников.
- `container-smoke.yml`: только workflow_call из CI/Full. BuildKit build один раз,
  затем существующий `--no-build` HTTP/queue/persistence/restart smoke. Нет моделей.
- `full-acceptance.yml`: workflow_dispatch, workflow_call (релизная подготовка),
  release prereleased/published. Это единственное место Whisper/Ollama, полного
  Windows lifecycle и воспроизводимости ZIP. После lifecycle выполняется одна
  installed API/UI приёмка с CPU + Ollama/переводом/конспектом/edit/export.
- `container-release.yml`: сохранены tag v*.*.* и workflow_dispatch. Перед старой
  публикацией GHCR/Compose вызывает Full Acceptance. Публикует именно принятые
  Windows ZIP/EXE/provenance и Docker image из artifacts текущего run без второй
  сборки. Registry image отдельно smoke-проверяется до создания GitHub Release.
  Автопубликация не запускается от PR.

Нет workflow_run, pull_request_target, privileged PR tokens или secrets:inherit.
PR jobs имеют contents:read. Права записи остались только у существующего publish
job; actions:read нужен ему для получения принятых artifacts.

## Concurrency и required check

CI group включает workflow, event и PR number (для PR) либо commit SHA (main).
Новый commit отменяет только старый run этого PR. Разные PR/main/workflow не
пересекаются. Main SHA сохраняет отдельные результаты. Full/release имеют отдельные
namespaces и run_id, cancel=false: ручной acceptance не отменяется push.

Рекомендуемый обязательный check: **required** из workflow CI. Он всегда выполняется,
зависит от changes, всей Fast matrix и обоих условных smoke jobs; success/skipped
допустимы, failure/cancelled блокируют. Поэтому документация не оставляет Pending.
Старые `windows`/`checks` не следует назначать обязательными: workflows удалены.
Branch protection менять должен владелец отдельно; здесь настройки не менялись.

## Кэши и целостность

- setup-python pip: OS/Python + платформенный lock и requirements-ci.txt.
- Windows raw embedded Python/VC runtime/Inno/WebView2 downloads и exact wheel cache:
  release-inputs.json, requirements-release.txt, release-wheels.json. Каждый input
  перед использованием проверяется существующими SHA256 guards; распакованные
  install payloads, workspace, secrets, SDK output и пользовательские данные не кэшируются.
- Docker BuildKit layers: Dockerfile + hash lock, fallback внутри этого набора;
  output image загружается локально, smoke не пересобирает его.
- Whisper cache только Full: component-manifest hash, проверяются bytes/SHA256.
- Ollama cache только Full: pinned installer manifest + model name, installer
  SHA256/signature/publisher и model blob integrity проверяет существующий harness.
- actionlint 1.7.7 имеет фиксированные SHA256 Linux/Windows архивов. Node 24.19.0,
  Python 3.12.10, pytest/Ruff/PyYAML закреплены. Actions закреплены commit SHA.

Smoke сохраняет лишь JSON (5 дней); Full сохраняет принятый Docker image 7 дней,
Windows дистрибутив и отчёты 14 дней,
при ошибке — только отчёты 7 дней. Fast вообще не публикует installer artifacts.

## Полная проверка и выпуск

В Actions → Full Acceptance → Run workflow выбрать нужный ref и public Ollama model
(по умолчанию qwen3.5:0.8b). Sandbox не нужен для каждого изменения; при изменениях
окружения отдельный существующий Run-Acceptance.ps1 запускается явно владельцем.

Manual/tag preparation собирает ZIP/EXE и записывает acceptance-provenance.json:
точный git SHA и SHA256 обоих файлов. Full тестирует эти же файлы. Для ручного
релиза следует загрузить принятые ZIP, EXE, SHA256SUMS.json и provenance из успешного
artifact без пересборки. Release-event скачивает эти uploaded assets и проверяет
хеши/SHA текущего tag, затем выполняет lifecycle/inference/UI на них. Отсутствие
assets/provenance, другой SHA или повреждение — FAIL, без fallback на rebuild.
Старые релизы без provenance требуют новой явной подготовки, не считаются принятыми.

GITHUB_TOKEN-created release не порождает новый workflow event по правилам GitHub;
tag publication уже прошла Full. Release-event проверка покрывает release, созданный
пользователем/внешним разрешённым инструментом. В этой задаче release не создавался.

## Локальная проверка

`python scripts/check-fast.py` использует уже установленное dev окружение и Node;
не устанавливает AI-компоненты и не скачивает модели. Нужные dev dependencies
описаны lockfiles и requirements-ci.txt. Единственная небольшая tool-загрузка —
проверенный actionlint; недоступный Node/зависимости дают ненулевой exit code.
`--config-only` проверяет YAML/expressions/policy без runtime; CI `--skip-config`
избегает повторения этой проверки, `--unit-only` запускает Windows suite без статики.

Локальные policy tests (20) покрывают матрицу путей/событий, обязательный gate,
concurrency и запреты моделей/installer lifecycle в Fast/Smoke. Не создаются
фиктивные коммиты для проверки отмены; её условия проверены статически. Для этого
инфраструктурного PR Full/Sandbox и загрузки моделей не запускаются. Реальный
PR-cycle подтверждает применённую маршрутизацию; результаты добавляются в PR.
