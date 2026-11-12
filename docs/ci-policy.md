# CI: стоимость, события и релизные артефакты

> Current workflow navigation: [testing](development/testing.md) and [release procedure](development/releases.md). Dated audit sections below describe their stated version; current YAML defines triggers.

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
  Python инструментов CI — предустановленный стабильный 3.12.x с check-latest=false; фактический patch виден в журнале setup-python. Python внутри Windows-дистрибутива остаётся закреплённым на 3.12.10. pytest/Ruff/PyYAML закреплены. Actions закреплены commit SHA.

Smoke сохраняет лишь JSON (5 дней); Full сохраняет принятый Docker image 7 дней,
Windows дистрибутив и отчёты 14 дней,
при ошибке — только отчёты 7 дней. Fast вообще не публикует installer artifacts.

## Полная проверка и выпуск

В Actions → Full Acceptance → Run workflow выбрать нужный ref. LLM HTTP boundary
заменяется фиксированными потоковыми ответами; Ollama и LLM-веса не скачиваются.
CPU Whisper остаётся реальным. Сохранение, редактор/экспорт, статья/конспект и
обработка неверного ответа проверяются штатным приложением. Это не тест качества LLM.
Отдельный manual workflow Model and prompt behavior проверяет реальную выбранную
модель и версионируемые промпты/примеры (см. model-behavior.md), не блокируя релиз.
Sandbox не нужен для каждого изменения; при изменениях
окружения отдельный существующий Run-Acceptance.ps1 запускается явно владельцем.

Manual/tag preparation собирает ZIP/EXE и записывает acceptance-provenance.json:
точный git SHA и SHA256 обоих файлов. Full тестирует эти же файлы. Для ручного
релиза следует загрузить принятые ZIP, EXE, SHA256SUMS.json и provenance из успешного
artifact без пересборки. Release-event скачивает эти uploaded assets и проверяет
хеши/SHA текущего tag, затем выполняет lifecycle/CPU Whisper/UI и LLM HTTP contract на них. Отсутствие
assets/provenance, другой SHA или повреждение — FAIL, без fallback на rebuild.
Старые релизы без provenance требуют новой явной подготовки, не считаются принятыми.

GITHUB_TOKEN-created release не порождает новый workflow event по правилам GitHub;
tag publication уже прошла Full. Release-event проверка покрывает release, созданный
пользователем/внешним разрешённым инструментом. В этой задаче release не создавался.

## Локальная проверка

Локальная последовательная сборка ZIP/EXE с очередью, post-merge hook для локального
main, provenance и preview очистки: [команды и границы](local-build.md).
Это не заменяет Full Acceptance и не устанавливает приложение автоматически.

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


08.11.2026: Inno Setup и actionlint скачиваются через scripts/download_build_file.py: до четырёх попыток при сетевой ошибке/HTTP 408, 429, 5xx, тайм-аут 30 секунд, паузы 2/4/8 секунд. Скачивание идёт в уникальный .part; кэш публикуется атомарно только после закреплённого SHA256. Корректный кэш не требует сети, повреждённый восстанавливается. Подпись издателя Inno Setup дополнительно проверяется PowerShell-скриптом; helper не выводит путь или сообщения в stdout, который используется для пути компилятора. Архив actionlint дополнительно кэшируется между CI jobs/runs и каждый раз проверяется по SHA256.

При повторной попытке actionlint/Inno Setup используют официальный api.github.com/repos/.../releases/assets/ID с Accept: application/octet-stream. ID закреплён вместе с версией; уникальный query исключает повтор закэшированного перенаправления. SHA256 и подпись не ослабляются, сторонние зеркала не используются.

08.11.2026: локальный post-merge использует полный кешируемый офлайн EXE, без изменения GitHub CI routing. Компоненты content-addressed и проверяются SHA256 архива на cache hit; CPU proof кешируется для одинакового backend/runtime/installer и хоста. Каждый merge сохраняет Fast tests и проверку точного полученного EXE (install/reinstall/health/uninstall в отдельном AppId). Полный ZIP/некешируемый путь и clean-VM/hardware acceptance остаются явными отдельными проверками.


### Граница публичного релиза — 09.11.2026

По уточнению владельца GitHub Releases предназначен только для стандартного пакета. Domestic и полный пакет из component cache остаются личными: переименование файлов не делает их публичными. `ci_artifacts.py` перед записью/проверкой provenance требует `profile=standard`, `domestic=null`, `whisper_weights_included=false`, отсутствие component cache и приватных файлов. Проверяется реальный список ZIP, а не только декларация manifest; неизвестные веса блокируются. Исключения ONNX ограничены точными SHA256 VAD из pinned faster-whisper и тремя тестовыми примерами pinned onnxruntime. Для VAD требуется отдельное уведомление Silero MIT, включаемое source allowlist сборщика. Это техническая граница, а не завершённый аудит всех транзитивных лицензий (см. THIRD-PARTY.md).

Publish job повторяет проверку в каталоге accepted-windows до registry push и gh release create. Посторонние ZIP/EXE в каталоге публикации запрещены. SHA256SUMS содержит только созданные текущим запуском артефакты, а не старые файлы по glob. Inno PublicRelease несовместим с Domestic/CachedComponents; lifecycle проверяет полное равенство manifest установленного EXE и принятого ZIP.

Модели Whisper, community-1 и LLM не переносятся из личного cache в public assets. Настройка после установки использует официальные источники и пользовательский доступ/согласие. Не сохранять токены в дистрибутиве. Наличие уже проверенной локальной модели не требует повторного скачивания, нового inference или HF-доступа.


### Windows release 0.9.0 — 09.11.2026

`windows-release.yml` — единственный автоматический publisher тегов `v*.*.*`. Run workflow на main подготавливает новый выпуск: BUILD увеличивается и коммитится перед созданием тега; Run workflow на существующем matching version tag повторяет проверку/публикацию без изменения BUILD. Feature ref отклоняется до тяжёлых работ. Тег обязан совпадать с release-inputs.json и указывать на commit в origin/main. Concurrency по ref не прерывает активный выпуск.

Verify повторно использует full-acceptance.yml с windows_only=true: та же Windows сборка, детерминированный rebuild, WebView/installer lifecycle и CPU functional acceptance с внешними fixture-моделями; container job пропускается. Manual Full и прежний Container release сохраняют полный профиль по умолчанию. Container release теперь запускается только вручную, не конкурирует за native version tags.

Publish имеет только contents:write/actions:read, получает accepted artifact текущего run без пересборки и повторяет public gate. scripts/windows_release.py повторно проверяет tag, revision, hashes и размер каждого файла (<2 GiB), загружает только четыре явно перечисленных файла. Релиз сначала draft; все четыре файла скачиваются и сверяются по SHA256 до публикации. Rerun дополняет только отсутствующие assets draft; существующие файлы не заменяются. Несовпадение байтов/посторонние файлы останавливают публикацию. Уже опубликованный полный релиз только сверяется, не перезаписывается. Release notes каждой сборки готовятся в docs/releases/next-build.md, переносятся в docs/releases/X.Y.Z-build.N.md и публикуются из tagged commit; прежние версионные notes docs/releases/X.Y.Z.md остаются обязательными для legacy тегов vX.Y.Z.

Для 0.9.0: merge проверенных изменений в main, push main, создать и отправить v0.9.0 на этот commit. GITHUB_TOKEN публикует релиз после уже пройденной приёмки, без рекурсивного release-event запуска. Пользовательский/external published release по-прежнему проходит существующую Full проверку точных assets.

Public gate дополнительно допускает только .py/.pyi исходники трёх известных dependency-каталогов models (ctranslate2, onnxruntime/transformers, tokenizers). Это не исключение для весов: .bin/.onnx и остальные запрещённые assets проверяются независимо от каталога. Перед повторным выпуском 0.9.0 правило проверено на полном составе закреплённых Windows wheels.


Номера билдов 0.9.0: GitHub использует N.A (номер запуска workflow и попытки), Local — сохраняемый атомарный N. Все шаги одной попытки, в том числе deterministic rebuild, получают одинаковую identity. Failed attempts расходуют номер. Source commit, global run id и workflow сохраняются в metadata; version X.Y.Z не меняется из-за нового билда. Повторная выдача готового локального пакета сохраняет его номер.

BUILD — единственный источник номера билда, обычный отслеживаемый текстовый файл с целым числом. Для 0.9.0 начальное значение 1. В последующих релизах prepare job на main увеличивает число, делает commit BUILD, атомарно отправляет main + новый version tag и явно dispatch-ит tagged workflow (GITHUB_TOKEN push сам не запускает второй workflow). Старый тег нельзя использовать для нового выпуска: повторные попытки сохраняют BUILD. Gate проверяет, что новый tag использует BUILD больше предыдущих version tags с таким файлом. Локальные сборщики только читают BUILD. Никаких файлов-счётчиков в .git/cache, номеров CI run/attempt и build-info.json не создаётся. Metadata номера хранится в уже существующих release-manifest/provenance и самом BUILD внутри пакета. Model readiness от номера не зависит.
