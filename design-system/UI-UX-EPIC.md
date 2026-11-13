# UI/UX Epic: постепенная стандартизация и вкладки рабочего пространства

Срез плана: 14.11.2026. Production и подтверждения проверок описаны ниже.
Это текущий backlog, не новый массовый
редизайн и не описание уже внедрённых workspace tabs. [PLAN](PLAN.md) — исторический
план завершённого переноса 19.10.2026. Обновлять статусы и evidence здесь при закрытии
задач; не создавать параллельный список в README или истории.

## Цель и границы

Постепенно унифицировать существующий HTML/CSS/JS UI, затем заменить избыточные
checkboxes меню «Вид» вкладками без потери функций. [MASTER](MASTER.md),
[CONTRACTS](CONTRACTS.md) и [workspace override](pages/workspace.md) описывают текущий
интерфейс. [WORKSPACE-TABS](WORKSPACE-TABS.md) — единственный проектный контракт
будущих вкладок, mapping панелей и открытых вопросов совместимости.

Не входят: новый framework, docking system, второй settings/state store, новые API,
переписывание backend/host/NPU, версия/BUILD, релиз или установка компонентов.

## Архитектурные решения

- Сохранить native WinForms/WebView2 host и shared web assets. `desktop-shell.js`
  компонует верхние команды, перемещая существующие controls, а не копируя их.
- `workspace-view.js` владеет только presentation preferences версии 1;
  `recording.js` — выбором материалов/независимых версий; `studio.js` — stage/report
  и навигацией. Новый UI не становится вторым владельцем этих состояний.
- Один плеер и один report iframe; конспект/статья используют общий редактор.
  Скрытие не сбрасывает playback, dirty state, Undo, revisions или выбранную речь.
- Переиспользовать tokens и `.vd-tabs`; CSS собирать через `build-ui-css.py`.
  Не вводить универсальный JS tab-controller до доказанной необходимости.
- Прогресс, ошибки, остановка и восстановление остаются вне переключаемых областей.
  Выбор вкладки не запускает обработку или генерацию.
- Вкладки «Расшифровка / Конспект / Статья» не эквивалентны независимым checkbox-комбинациям.
  [Решения Task 7](WORKSPACE-TABS.md#решения-task-7--13112026) задают precedence,
  default/reset, историю и original+translation. До доказанной parity сохраняются
  compatibility view и прежние controls; схема v1 не меняется.

## Завершено

| ID | Результат | Зависимости | Критерий / evidence |
| --- | --- | --- | --- |
| 1 | Проектный контракт вкладок — `60dbb2e` | Аудит архитектуры | Mapping всех пунктов «Вид», owners, guards, открытые вопросы; production не менялся |
| 2 | Characterization preferences v1 — `b88824c` | 1 | Частичные/неверные значения, неизвестные поля, отсутствие записи при чтении, сохранение известных настроек; Node harness PASS |
| 3 | Keyboard пропускает скрытое «Вид» — `e82474b` | Текущий shell | Left/Right в обе стороны, wraparound, закрытие меню и Escape; recording/library browser regressions |
| 4 | Общий `.vd-tabs`, первым подключены настройки — `a5e9f00` | Существующие tokens/tabs | Общие selected/hover/focus/forced-colors, прежние ID/ARIA/handlers; CSS bundle и settings browser checks |
| 5 | `.vd-tabs` для «Конспект / Статья» — `47d5739` | 4 | Equal widths, 8/16 px, keyboard/dirty/Undo/save, empty article, visibility и responsive scenarios PASS |
| 6 | API-free [прототип workspace tabs](prototype/workspace-tabs.html) — `52feee5` | 1, 5 | Edge: 60 сочетаний размера/состояния/области, keyboard/focus, empty article, persistent player/textarea, stop/recovery; без API/storage/history |
| 7 | [Решения совместимости и тестовая матрица](WORKSPACE-TABS.md#тестовая-матрица-task-7) | 1, 2, 6 | URL выше flags без save, default/reset, local tabs без новых history entries/store, compatibility view для v1, original/ru/both; 256 preference cases и storage failures, production gates явно отделены |
| 8 | Workspace с расшифровкой, URL и storage guards | 6, 7 | Существующие DOM/player/editor; fixture-проверки polling, keyboard/focus, deep links, guards и storage; legacy history fallback описан ниже |

Tasks 1–7 и этот backlog присутствуют на `origin/main` (`450a72e`, проверено
13.11.2026). Task 7 добавил контракт совместимости и characterization; на этом
срезе production tabs ещё отсутствовали. Интегрированы commits `47d5739` (Task 5), `659a8a0` (backlog),
`52feee5` (Task 6), `77dacb0` (scoped Terra executor) и `450a72e` (Task 7). Это
не выпуск Windows-пакета.

Сопутствующие изменения: `934e512` ускоряет тестовые fixtures без production-правок;
`278ecb9` вводит переиспользуемый Sol → Terra workflow, `77dacb0` добавляет восемь
шагов и task-specific read/edit permissions с default-deny; оба находятся в main.
Роли и ограничения описаны в [agent workflows](../docs/development/agents.md),
не дублируются новой конфигурацией или skill.

Проверки Task 5: Fast — **847 passed, 4 skipped**, плюс **29** config checks;
Edge `--material-tabs-only`, `--material-tabs-empty`, `--workspace-view-only`,
`--spacing-only`. Повтор параллельно с Fast потерял HTTP-ответ save; итоговые
последовательные material scenarios прошли без ослабления assertions. Это fixture
evidence, не installed WebView2, Windows scaling или hardware acceptance.
При интеграции повторный Fast и четыре Edge scenarios прошли; workspace fixture
потребовал повторов после CDP reload error и сбоя fetch-trap assertion. Проверки не ослаблялись.

## Осталось

Каждая строка — отдельный проверяемый increment; крупную интеграцию делить дальше
до правок. Порядок определяется зависимостями, а не только номером.

| ID | Небольшой результат | Зависимости | Приёмка | Исполнение |
| --- | --- | --- | --- | --- |
| 9a | Убрать отдельную область перевода из UI записи, не удаляя механизм и данные | 8 | Нет отдельной вкладки перевода и её controls; сохранены результаты, backend, восстановление и независимые операции конспекта; отсутствие доступа к переводу в UI явно документировано | Реализовано; browser evidence ниже, installed WebView2 не проверен |
| 9b | Единый ряд «Расшифровка / Конспект / Статья» рядом с видео, на узком экране под ним | 8, 9a | Один плеер и iframe; переходы по таймкодам конспекта управляют тем же плеером; independent versions, notes/article/empty, dirty navigation и Undo; нет автогенерации или смены речи; совместимый вид сохранён | Не выполнено |
| 10 | Убрать только заменённые checkbox-controls | 9a, 9b и доказанная parity | Для оставшихся пунктов/сочетаний из mapping есть доступный эквивалент; layout/reset/video hide сохранены; help/docs/harness refs синхронизированы | Не выполнено |

Скрытие перевода не удаляет сохранённые переводы и не изменяет обработку уже
запущенных заданий. Новые конспекты не запускают дополнительный перевод; создание
статьи также не запускает перевод реплик. Поддержка произвольных языков ещё не реализована.

**Task 8 завершён; 9a реализован, следующий increment — 9b.**
Production содержит переключатель расшифровки и совместимого вида. Перевод убран
из UI без удаления backend и данных. Task 9b объединяет расшифровку, конспект и статью
в одном ряду без промежуточной вкладки «Материалы». Действие перевода рядом с
расшифровкой и выбор языка отложены в [issue #10](https://github.com/IavnFGV/video-descriptor/issues/10).

| Slice | Результат и проверка | Зависимости | Модель |
| --- | --- | --- | --- |
| 8a | Готово: workspace tablist расшифровки и прежнего вида, существующий DOM/feed, локальный выбор; focused browser scenarios | Task 7 на `origin/main` | Реализация и локальная проверка |
| 8b | Готово: URL precedence, transient раскрытие, hash и guarded Back/Forward; fallback заменяет текущий history entry при отказе | 8a; контракт Task 7 | Focused browser checks |
| 8c | Готово: отказ чтения/записи `localStorage` в затронутых controllers, проверка полной fixture-страницы и reload | Task 7 | Ключи и данные без миграции |
| 8d | Готово: production DOM, keyboard/focus, polling, выбранные deep links, guards и storage failures проверены в fixtures | 8a–8c | Границы проверок перечислены в evidence |

Подключение конспекта и статьи в общий ряд остаётся следующим increment (Task 9b); доступ к прежней
комбинации оставшихся панелей сохранён. Весь Task 9 ещё не завершён.

### Evidence Task 9a

- Убраны отдельная область и пункт «Вид», режимы/экспорт перевода, поля в редакторе
  реплик, галочки после конспекта и пункт промпта. Новые отчёты показывают оригинал,
  файлы перевода остаются. Shared provider credentials и старые задания не меняются.
- `--translation-retired`: старый flag=true не раскрывает UI; старый checked draft
  не меняет `translate_after:false`; реальная правка оригинала сохраняет перевод;
  проверены четыре размера и native settings в Edge. Это fixture, не installed host.
- Backend cleanup ограничен удалением frontend discovery: общие сервисы и tests
  нужны другим операциям и восстановлению. Анализ — в
  [translation-providers](../docs/translation-providers.md#границы-очистки-backend).
- Installed WebView2 и Windows scaling остаются непроверенными; их приёмка не закрыта.
- Итоговый Fast: **860 passed, 3 skipped**, **29 config checks passed**; Ruff,
  JS syntax, CSS bundles и UI audit PASS. Edge: `--translation-retired`,
  `--workspace-tabs-only`, `--workspace-view-only`, `--material-tabs-only`,
  `--material-tabs-empty`, `--release-harness-only` PASS. Captures просмотрены;
  сохранены в ignored `windows-app/runtime/zero-config/unified-recording/`.

### Evidence Tasks 8b/8c

- `studio.js` и `recording.js` переживают отказ storage для существующих настроек
  speech-engine и playback-link; доступность в текущем документе не обещает запись
  на диск. Изолированные Edge `--workspace-storage-read` и `--workspace-storage-write`
  проверяют открытие записи, работу controls, reset и reload.
- Paint материала не переписывает URL; явный выбор материала и stage сохраняет hash
  и `history.state`. Изолированный Edge `--workspace-route-writers` и существующие
  material/workspace fixtures прошли. Guard iframe проверяется до закрытия quick edit;
  один запуск прошёл assertions, но завершился timeout при закрытии Edge; повтор прошёл.
- Fast `--workers 4`: **841 passed, 1 skipped** в параллельной фазе,
  **16 passed, 2 skipped** в последовательной; config checks и UI audit прошли.
- До интеграции 8b popstate обрабатывался разными owners. Текущий coordinator сначала
  проверяет черновики, затем применяет существующие owners; при отказе восстанавливает
  прежний URL через replaceState. Для старых browser history entries это может изменить
  следующий Back/Forward, но не заменяет пользовательские правки. Это ограничение
  относится к браузерной истории; отдельного history UI в приложении нет.
- Дополнительные изолированные Edge checks: `--workspace-deep-link` проверяет
  приоритет material над stage и временное раскрытие при flag=false;
  `--workspace-missing-report` — отсутствие подстановки другого материала;
  `--workspace-storage-event` — сохранение фокуса при событии storage. Существующие
  material/workspace fixtures проверяют отказ перехода с реальными черновиками
  конспекта и реплики. Installed WebView2 и Windows scaling отдельно не проверялись.
- Итоговый Fast после последних правок: **841 passed, 1 skipped** в параллельной
  фазе и **16 passed, 2 skipped** в последовательной; config checks и UI audit PASS.

### Evidence Task 8a

- Две локальные вкладки используют общий существующий DOM; «Все включённые панели»
  возвращает сохранённые flags. Изменение checkbox явно возвращает совместимый вид.
  Вкладки не записывают preferences и не меняют URL или историю.
- Изолированный Edge fixture: `--workspace-tabs-only`, `--workspace-view-only`,
  `--material-tabs-only`, `--material-tabs-empty`; Node characterization preferences.
  Вкладки и refresh сохраняют объекты player/feed/frame; проверены клавиши, фокус,
  интервал polling и размеры fixture.
- URL precedence, guarded Back/Forward, смена записи и storage failures всей страницы
  остаются gates 8b–8d. Installed WebView2, Windows scaling и аппаратная приёмка
  не проверены. Сам по себе этот slice не закрывает Task 8.
- Fast с `--workers 4` не запустил параллельную suite: в окружении отсутствует
  pytest-xdist. Последовательный Fast: **836 passed, 4 skipped, 13 failed, 7 errors**;
  конфигурационные проверки и UI audit прошли. В журнале отсутствуют FFmpeg,
  `tokenizers`, `faster_whisper` и `markdown_it`; этот запуск Fast не прошёл.
- После установки недостающих зависимостей в `.venv` повторный Fast `--workers 4`
  прошёл: **841 passed, 1 skipped** в параллельной фазе, **16 passed, 2 skipped**
  в последовательной фазе; конфигурационные проверки и UI audit также прошли.

### Evidence Task 7

- Base `6d4c15c`, branch `codex/ui-ux-task7-compatibility`. Sol: архитектурные решения,
  review и validation; Terra: только `tests/workspace_view.cjs`, read-only input —
  `video_descriptor/assets/workspace-view.js`. Один implementation handoff и одна
  targeted correction (реальный `report=` в URL case, точный PASS message).
- Effective executor проверен в task Location до обоих handoffs: Terra Standard,
  восемь шагов, exact grants после deny; после завершения grants сняты и effective
  default-deny восстановлен. Production JS/CSS/HTML, API, schema, BUILD не меняются.
- Node VM проверяет все 128 масок × 2 layout без записи при чтении, URL neutrality
  текущего presentation controller, отдельные read/write failures, reset/reload,
  storage events и embedded=1. Это не проверка будущих URL overrides/Back/Forward.
- Focused `tests/test_workspace_view.py`: **3 passed**; Node harness и syntax PASS;
  **81** локальная Markdown target/anchor проверена. In-memory mutation check
  отклоняет потерю v1 flag, лишнее storage reread, storage access в embedded и
  зависимость preferences от URL; production-файлы для этого не изменялись.
- Финальный `check-fast.py`: **852 passed, 4 skipped**, плюс **29** config checks;
  Ruff, production CSS bundles и статический UI contract audit PASS.
- Browser gates H2 и сохранение hash не объявлены пройденными: текущие route owners
  не обеспечивают полную material/job/folder popstate parity. Существующие браузерные
  fixtures не запускались заново: production DOM/CSS и прототип не меняются.

### Evidence Task 6

- Base `bf0d4c4`; Terra allowed path: только новый
  `design-system/prototype/workspace-tabs.html`. Один вызов `executor` завершился
  step limit без patch; прототип реализован и проверен Sol без повторного вызова.
- Прототип использует общие tokens/components и `.vd-tabs`; состояния ready, empty,
  busy, error меняют только DOM. Плеер, прогресс, ошибка, stop/recovery вне вкладок.
- `scripts/verify-workspace-prototype.py`: 1440×900, 1200×820, 1024×768, 760×560,
  375×820; mouse, Left/Right/Home/End, wraparound, Tab/Shift+Tab, visible focus,
  nested tabs, hidden panels, исходный player/textarea и сохранение черновика.
  Запрещённые API/storage/history calls проверяются runtime traps; запросы — только
  HTML/CSS и favicon. Captures включают forced-colors и zoom-equivalent viewport.
- Снимки и JSON находятся в ignored `windows-app/runtime/zero-config/workspace-prototype/`.
  Это Edge fixture, не installed WebView2, Windows scaling или hardware acceptance.
  Медиа не загружается; playback, настоящий iframe, Undo/revisions/dirty guards
  production здесь не моделируются. Прототип не подключён к приложению.
- Итоговый Fast: **847 passed, 4 skipped**, плюс **29** config checks; CSS bundle
  и UI contract audit PASS. Первый запуск остановлен лимитом команды 120 секунд;
  повтор с увеличенным timeout завершился за 181 секунду без ослабления проверок.
  Prototype JS syntax, Ruff и локальные Markdown link targets также проверены.
- При интеграции `52feee5` и `77dacb0` повторены полный Fast — **852 passed,
  4 skipped**, плюс **29** config checks — и все **60** prototype browser scenarios.
  Прототип и executor сохранены без новых implementation-правок. Post-merge hook
  обойдён только для этой интеграции: build и restart preview не запускались.

## Общий gate и передача работы

- На каждом затронутом UI проверить mouse/keyboard, один Tab-stop в tablist,
  Left/Right/Home/End, видимый focus, empty/long/busy/error и hidden-panel states.
- Сохранить IDs/handlers/API payloads, routes/query/hash, Back/Forward, revisions,
  manual edits и guards; не менять baseline для обхода audit.
- Проверить реальные CSS/DOM и визуальные captures, не только строковые assertions.
  Размеры/zoom/scaling — по MASTER; отдельно отмечать то, что не проверялось.
- Использовать существующие material/workspace browser fixtures и focused tests;
  CSS `--check`, UI audit и финальный Fast — по [testing guide](../docs/development/testing.md).
  Для docs-only допустим `check-fast.py --config-only` плюс отдельная проверка ссылок.
- Terra непосредственно исследует, реализует и проверяет изменения, включая CSS и
  operational docs. Sol доступен как контекстный советник для сложных решений или
  при блокировке; подробнее — в [agent workflows](../docs/development/agents.md#terra-primary-and-sol-advisor).
  Архитектура и migration/dirty-state integration требуют отдельного анализа.
- Использовать dedicated task branch, отдельный worktree для concurrent mutations.
  Проверенный commit — единица отката; пользовательские данные не откатывать.
  Публикация отдельна от реализации; перед merge проверить build/preview hooks.
