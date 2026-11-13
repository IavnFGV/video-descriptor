# UI/UX Epic: постепенная стандартизация и вкладки рабочего пространства

Срез: 13.11.2026, реализация до `47d5739`. Это текущий backlog, не новый массовый
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
- «Расшифровка / Перевод / Материалы» — направление, не готовая эквивалентность
  независимых checkbox-комбинаций. URL/preferences precedence, первое открытие,
  Back/Forward и просмотр перевода вместе с оригиналом ещё требуют решения в Task 7.
  До него не менять схему хранения и не удалять старые настройки/контролы.

## Завершено

| ID | Результат | Зависимости | Критерий / evidence |
| --- | --- | --- | --- |
| 1 | Проектный контракт вкладок — `60dbb2e` | Аудит архитектуры | Mapping всех пунктов «Вид», owners, guards, открытые вопросы; production не менялся |
| 2 | Characterization preferences v1 — `b88824c` | 1 | Частичные/неверные значения, неизвестные поля, отсутствие записи при чтении, сохранение известных настроек; Node harness PASS |
| 3 | Keyboard пропускает скрытое «Вид» — `e82474b` | Текущий shell | Left/Right в обе стороны, wraparound, закрытие меню и Escape; recording/library browser regressions |
| 4 | Общий `.vd-tabs`, первым подключены настройки — `a5e9f00` | Существующие tokens/tabs | Общие selected/hover/focus/forced-colors, прежние ID/ARIA/handlers; CSS bundle и settings browser checks |
| 5 | `.vd-tabs` для «Конспект / Статья» — `47d5739` | 4 | Equal widths, 8/16 px, keyboard/dirty/Undo/save, empty article, visibility и responsive scenarios PASS |

Tasks 1–4 находятся в main. Task 5 завершён и закоммичен локально, **не включён
в main и не отправлен** на момент этого среза. Не представлять его как опубликованный.

Сопутствующие изменения: `934e512` ускоряет тестовые fixtures без production-правок;
`278ecb9` вводит переиспользуемый Sol → Terra workflow и находится в main.
Роли и ограничения описаны в [agent workflows](../docs/development/agents.md),
не дублируются новой конфигурацией или skill.

Проверки Task 5: Fast — **847 passed, 4 skipped**, плюс **29** config checks;
Edge `--material-tabs-only`, `--material-tabs-empty`, `--workspace-view-only`,
`--spacing-only`. Повтор параллельно с Fast потерял HTTP-ответ save; итоговые
последовательные material scenarios прошли без ослабления assertions. Это fixture
evidence, не installed WebView2, Windows scaling или hardware acceptance.

## Осталось

Каждая строка — отдельный проверяемый increment; крупную интеграцию делить дальше
до правок. Порядок определяется зависимостями, а не только номером.

| ID | Небольшой результат | Зависимости | Приёмка | Исполнение |
| --- | --- | --- | --- | --- |
| 6 | API-free прототип workspace tabs на существующих primitives | 1, 5 | Wide/narrow, пустой материал, активная операция/ошибка; плеер и recovery доступны; без API/генерации | Terra: bounded prototype patch; Sol: visual review |
| 7 | Решения совместимости и тестовая матрица в WORKSPACE-TABS | 1, 2, 6 | Явные URL/preferences precedence, default/reset, Back/Forward, storage failure, v1-комбинации и доступ к переводу с оригиналом; нерешённые вопросы не скрыты | Sol; Terra только для отдельных characterization tests |
| 8 | Первый production slice: переключение workspace с расшифровкой | 6, 7 | Те же DOM/player/editor, устойчивость к polling, keyboard/focus, deep links и guards; прежние возможности доступны во время перехода | Sol-led integration; без нового state manager |
| 9a | Подключить существующую область перевода | 8 | Настройки, original/translation modes, версии и экспорты доступны; переключение не запускает перевод; stale/dirty guards сохранены | Sol-led; механические правки можно Terra |
| 9b | Подключить «Материалы» с прежними subtabs | 8, 9a | Один iframe, independent versions, notes/article/empty, dirty navigation и Undo; нет автогенерации или смены речи | Sol-led; отдельные bounded patches Terra |
| 10 | Убрать только заменённые checkbox-controls | 9a, 9b и доказанная parity | Для каждого пункта/сочетания из mapping есть доступный эквивалент; layout/reset/video hide сохранены; help/docs/harness refs синхронизированы | Sol: parity review; Terra: отдельные механические slices |

**Следующий increment — Task 6, пока не начат.** Сначала определить конкретные
allowed paths и состояния прототипа. Этот backlog не запускает следующую реализацию,
push, merge или релиз автоматически.

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
- Sol задаёт base SHA, максимум два allowed files, excerpts, invariants и acceptance
  для Terra `executor`; worker возвращает предложение без tools. Sol проверяет diff,
  применяет, собирает CSS, обновляет operational docs и запускает checks. Архитектуру,
  migration/dirty-state integration не отдавать как механическую задачу.
- Использовать dedicated task branch, отдельный worktree для concurrent mutations.
  Проверенный commit — единица отката; пользовательские данные не откатывать.
  Публикация отдельна от реализации; перед merge проверить build/preview hooks.
