# Поэтапный редизайн

19.10.2026: направление согласовано владельцем. Этап 0 завершён; этап 1 и компоновка главной/настроек из этапа 2 реализованы. См. IMPLEMENTATION.md. Далее — `/create` и библиотека, затем общие диалоги/редактор. API-унификация и аппаратная приёмка не включены в текущие UI commits.

Все этапы сохраняют HTML/CSS/JS и WebView2. Оценки — ориентиры разработки, не обязательство по сроку; аппаратная приёмка отдельно.

| Этап | Объём | Gate / проверка | Откат / риск | Оценка |
|---|---|---|---|---|
| 0 — текущий | аудит, MASTER/tokens/reference components, isolated main prototype, baseline contracts | согласование иерархии/навигации/визуального языка; production hashes совпадают | удалить только новые reference artifacts; рабочий UI не затронут | 1 этап |
| 1 — primitives | подключить tokens и scoped vd-* в главной; заменить кнопки, labels, focus, status/progress по одному компоненту | ids и handlers остаются, mocked states + keyboard/contrast + desktop tests | отдельный commit на компонент; старые CSS удалять только после миграции селекторов | 1–2 дня |
| 2 — главная и AI | компактная форма и readiness; checklist обязательной настройки, optional отдельно; единый picker для медиа/WAV + folder pattern | upload 202/raw/query/progress; probe/consent/cancel; compute snapshot; функциональные setup тесты в temp workspace | не менять API; сначала opt-in dev preview, затем default после проверки | 1–2 дня |
| 3 — workspace | общая оболочка для create/library; навигация и stages; настройки отдельно от generation/export; устранить дублирование названий | сохранить query job/folder/stage/report, dirty guards, Back/Forward, rerun/delete confirmations; 760×560 и scaling | не объединять native/postprocess и notes-run backend; поэкранные commits | 2–3 дня |
| 4 — editing / postprocess | вынести inline dialog CSS в shared reference; единые transcript/translation controls; notes iframe chrome | edit/split/revision conflict, draft recovery/Ctrl+S, versions; без потери segment ids/timing | сначала внешний shell, затем внутренности iframe; не переносить редактор на новый framework | 1–2 дня |
| 5 — exports / release | общая export панель и status model; empty/offline/recovery; убрать устаревшие CSS только после поиска refs | сверка содержимого SRT/VTT/TXT/MD, длинная запись, отсутствие речи; WebView2 download/navigation; regression suite | UI-only rollback commit/пакет; данные/модели не мигрируют | 1–2 дня + приёмка |

Порядок внутри этапа: инвентаризация refs → добавить новый opt-in компонент → привязать существующий handler → проверить состояния → визуальный и keyboard review → удалить заменённый CSS → commit. Не менять разметку, API и job state machine одним commit. При изменении baseline требуются объяснение diff и повторное contract-review, а не механическое обновление SHA.

## Приёмка перед массовым переносом

- Согласовать навигацию «Записи / Настройки AI / Диагностика» и компактную форму.
- Подтвердить один зелёный акцент, Segoe UI, высоту controls 40 px, спокойные поверхности.
- Согласовать сохранение device selector доступным в параметрах записи с явным scope «для новых заданий».
- Прототип не доказывает загрузку медиа, AI readiness или работоспособность backend; это отдельные gates следующих этапов.

Изоляция: ветка `design/ui-ux-audit`, отдельный worktree. Не merge/rebase и не менять Ollama/Sandbox соседней ветки. Push не выполнять. Редизайн существующих экранов начинается только после решения владельца по этапу 0.
