# UI/UX Epic: постепенная стандартизация и вкладки рабочего пространства

Срез: 13.11.2026, production до `47d5739`, прототип Task 6 и контракт Task 7 — ниже.
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
- «Расшифровка / Перевод / Материалы» не эквивалентны независимым checkbox-комбинациям.
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

Tasks 1–7 и этот backlog присутствуют на `origin/main` (`450a72e`, проверено
13.11.2026). Task 7 добавил контракт совместимости и characterization; production
tabs не реализованы. Интегрированы commits `47d5739` (Task 5), `659a8a0` (backlog),
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
| 8 | Первый production slice: переключение workspace с расшифровкой | 6, 7 | Те же DOM/player/editor, устойчивость к polling, keyboard/focus, deep links и guards; прежние возможности доступны во время перехода | Sol-led integration; без нового state manager |
| 9a | Подключить существующую область перевода | 8 | Настройки, original/translation modes, версии и экспорты доступны; переключение не запускает перевод; stale/dirty guards сохранены | Sol-led; механические правки можно Terra |
| 9b | Подключить «Материалы» с прежними subtabs | 8, 9a | Один iframe, independent versions, notes/article/empty, dirty navigation и Undo; нет автогенерации или смены речи | Sol-led; отдельные bounded patches Terra |
| 10 | Убрать только заменённые checkbox-controls | 9a, 9b и доказанная parity | Для каждого пункта/сочетания из mapping есть доступный эквивалент; layout/reset/video hide сохранены; help/docs/harness refs синхронизированы | Sol: parity review; Terra: отдельные механические slices |

**Следующий increment — Task 8, пока не начат.** Task 7 фиксирует контракт, не
production tabs. Выполнять Task 8 отдельными slices:

| Slice | Результат и проверка | Зависимости | Модель |
| --- | --- | --- | --- |
| 8a | Включить workspace tablist для расшифровки: существующий DOM/feed, presentation-only выбор, polling и focus не сбрасывают состояние; focused browser scenarios | Task 7 на `origin/main` | Sol ведёт архитектуру и интеграцию; Terra — только заранее ограниченную механику |
| 8b | Согласовать deep links, URL/hash и guarded Back/Forward по существующим owners; проверить конфликты и отказ guard | 8a; контракт Task 7 | Sol — route/guard дизайн и review; Terra допустим для точечных правок после декомпозиции |
| 8c | Изолированно обработать недоступность `localStorage` в затронутых controllers, без изменения ключей/данных; проверить ошибки чтения/записи и reload | Task 7; до полного acceptance. Параллельно с 8a/8b — только в отдельном worktree | Sol задаёт поведенческие границы; Terra возможен для строго ограниченного patch и тестов |
| 8d | Проверить production DOM, keyboard/focus, polling, deep links, guards и storage failures; закрыть Task 8 только по evidence | 8a–8c | Sol выполняет review и validation; отчёт worker не заменяет проверки Sol |

Multi-panel compatibility view и подключение перевода/материалов остаются
следующими increments (Tasks 9a/9b), не частью Task 8. Этот backlog не запускает
реализацию, push, merge или релиз автоматически.

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
