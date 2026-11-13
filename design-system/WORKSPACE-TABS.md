# План: вкладки рабочего пространства записи

Это проектный контракт последующих slices. Task 8a добавил локальные вкладки
расшифровки и совместимого вида, но не подключил вкладки перевода/материалов и
не изменил routing. Текущий вид и
правила меню «Вид» описаны в [workspace.md](pages/workspace.md); общие требования
компонентов и маршрутов — в [MASTER](MASTER.md) и [CONTRACTS](CONTRACTS.md).
Статусы задач, зависимости и порядок внедрения — в [UI/UX Epic](UI-UX-EPIC.md).

## Изолированный прототип Task 6

[workspace-tabs.html](prototype/workspace-tabs.html) открывается локально в браузере
и использует только общие tokens/components. Селектор демонстрирует готовую запись,
пустую статью, активную операцию и ошибку с имитацией восстановления. Один плеер и
общий textarea остаются в DOM; API, storage и production scripts не подключены.
Textarea — иллюстрация компоновки, не замена редактору с независимыми версиями.
Открытие перевода рядом с оригиналом иллюстрирует решение Task 7 ниже, но не
доказывает совместимость с production-редактором.
Команда повторной проверки — в [testing guide](../docs/development/testing.md#workspace-tabs-prototype).
Прототип не меняет текущее меню «Вид», маршруты или preferences.

## Предлагаемая компоновка

В открытой записи вкладки рабочего пространства переключают области
«Расшифровка», «Перевод» и «Материалы». Общий плеер остаётся доступен рядом с
выбранной областью; на узком экране области располагаются последовательно.
В «Материалах» остаются существующие вкладки «Конспект» и «Статья» с одним
редактором. Прогресс, ошибки, остановка и восстановление доступны вне скрываемых
областей. Переключение вкладки не запускает обработку или генерацию.

| Текущий пункт «Вид» | Предлагаемое место или поведение |
| --- | --- |
| Видео | Общий плеер; возможность скрыть и вернуть его должна сохраниться. |
| Расшифровка | Вкладка «Расшифровка»; доступ к тексту и экспорту сохраняется. |
| Участники | Контекстные действия рядом с расшифровкой; доступность управления сохраняется. |
| Перевод | Вкладка «Перевод»: настройки и прежний просмотр original/ru/both; оригинал доступен вместе с переводом без второй копии текста. |
| Конспект, статья / отчёт | «Материалы» и существующие вложенные вкладки; независимый выбор версий сохраняется. |
| Технические сведения и параметры | Контекстное раскрытие настроек и сведений, в том числе до готовой расшифровки. |
| Рядом / друг под другом; сброс | Сохранить выбор расположения и способ восстановить рабочий вид. |

Эксклюзивные вкладки не эквивалентны независимым сочетаниям видимости. До доказанной
parity остаются старые controls и доступный режим «Все включённые панели» с прежней
компоновкой. Удалять его вместе с checkbox-controls в Task 10 можно только после
проверки каждого действия и сочетания; при отсутствии эквивалента удаление блокируется.

## Состояние и совместимость

- `workspace-view.js` сейчас владеет только presentation preferences
  `video-descriptor:ui:workspace` версии 1; новый интерфейс не должен становиться
  вторым владельцем записей, заданий или редакторов.
- `recording.js` сохраняет выбор материалов и независимые версии, `studio.js` —
  существующее состояние stage/report и навигацию. Использовать эти владельцы,
  не создавать копии плеера, iframe или редакторов.
- Скрытие области само по себе не переключает материал и не уничтожает черновик.
  Переход, который меняет материал или версию, использует существующий dirty guard;
  сохранить revision, Undo, ручные правки и выбранную расшифровку.
- Сохранить `/`, `?job=`, `/create?folder=&stage=&report=`, `material`, hash и
  Back/Forward. Вкладки используют семантику и клавиатуру из MASTER.

## Решения Task 7 — 13.11.2026

Это целевой контракт для Tasks 8–10; routing и вкладки перевода/материалов ещё не реализованы. Production
сохраняет меню «Вид». Проверенная база: `6d4c15c`; исходники
`workspace-view.js`, `studio.js`, `recording.js` в
[shared assets](../video_descriptor/assets/). Новый store, schema v2, backend API,
query-параметр или hash для workspace tab не вводятся.

### Владельцы и приоритет

1. Существующие route controllers сначала разрешают `job`/`folder`, запись и версии
   с прежними guards; вкладка не выбирает другую запись, речь или материал сама.
   `workspace-view.js` остаётся единственным владельцем presentation preferences.
2. Для будущей видимой области явно заданный URL выше сохранённых flags:
   допустимый `material=notes|article` → «Материалы» и указанный subtab;
   иначе непустой `report` → «Материалы» с выбором через существующего owner;
   иначе `stage=notes` → «Материалы», `stage=speech` → «Расшифровка».
   Наличие допустимого `material` считается целью независимо от происхождения URL:
   старый нормализованный `material=notes&stage=speech` откроет «Материалы»;
   доступ к речи сохранён через вкладку, URL не очищается эвристически.
   При конфликте `material` определяет область/kind, но не позволяет подменить
   несовместимый или отсутствующий `report` другой версией: показать объяснение.
   `stage=source` сохраняет путь источника/параметров; не становится новой workspace
   вкладкой. На пустом `/create` остаётся создание, вкладки записи не показываются.
3. Явная цель временно раскрывается даже при её flag=false. Это override текущего
   представления, не запись в localStorage и не включение других панелей.
   Неизвестные `stage`/`material` не получают нового смысла; используются прежние
   route fallback и затем правило первого открытия. Не переписывать URL только ради
   выбора визуальной вкладки. Существующие `/`, `?job=`, `/create?...`, прочие query
   и hash сохраняются; существующие hash-маршруты не переопределяются вкладками.
4. Без явной цели: при нескольких включённых контентных областях открыть «Все
   включённые панели»; при одной — её вкладку. Контентные области: transcript,
   translation, notes/article (последние вместе считаются «Материалами»). Если
   контент скрыт целиком, не включать его молча: видимость плеера определяется video,
   доступные сведения и подсказка восстановления остаются. Наличие готового
   результата не меняет этот выбор.
   В материалах без explicit kind owner сохраняет текущий kind, при первом открытии
   предпочитает notes, если он включён, иначе article. Это presentation choice,
   не автоматический выбор версии/запуск/загрузка другого материала.
5. Обычный клик workspace tab временно показывает выбранную область, не меняя
   сохранённую маску v1 и другие flags. «Все включённые панели» возвращает исходную
   маску/компоновку, снимая временное раскрытие. Не хранить last-tab, layout или
   версии во втором store. Внутри текущего документа polling не сбрасывает выбор;
   переход к другой записи заново применяет URL и правило первого открытия.

### Default, reset и storage

- Точные defaults v1: `layout=side`; video/transcript/speakers=true;
  translation/notes/article/technical=false. До 1000 px side визуально становится
  вертикальным, но сохранённый side не заменяется stacked. Явный stacked действует
  и на широком экране. Скрыть/вернуть видео можно независимо от вкладки.
- Сохраняется ключ `video-descriptor:ui:workspace`, `version:1`, семь flags и два
  layout. Все 128 масок × 2 layout допустимы, включая all-false и notes+article.
  Последнее сохраняет доступ к обоим subtabs, не создаёт второй iframe.
- Чтение не пишет: отсутствующее, malformed, неподдерживаемая version → defaults;
  частичные v1 дополняются defaults, неправильные типы игнорируются, unknown fields
  не применяются. Уже существующий явный save сохраняет известные поля, опуская
  unknown fields; это не новая миграция и не разрешение на eager rewrite.
- «Восстановить вид» возвращает только presentation defaults и снимает временный
  выбор/override; URL-цель остаётся выше defaults и продолжает быть доступной.
  Reset не очищает URL, черновики, версии, Undo, playback или editor storage.
- Ошибка getItem → безопасные defaults в памяти; ошибка setItem → controls/reset
  работают в памяти, старые bytes не меняются. Reload снова читает старые настройки,
  если чтение доступно; долговременное сохранение при отказе не обещается.
- `storage` для этого ключа или `key=null` перечитывает маску без записи; чужой ключ
  ничего не меняет. В будущем обновление маски не должно сбрасывать активную область,
  прятать сфокусированный editor или отменять URL override; это browser gate, не
  установленное свойство текущего controller. Embedded report вообще не читает и
  не пишет workspace preferences.

### История, dirty guards и перевод

- Клик новой workspace tab — локальное presentation action без pushState и новых
  entries. Reload без явного route восстанавливает v1, а не последнюю вкладку.
  Existing material selection сохраняет свой `material`/replaceState contract;
  существующие stage/report переходы остаются у studio, не дублируются новым owner.
- На Back/Forward сначала применяется существующий guarded переход, затем область
  вычисляется по URL. Простой hide/show того же DOM не требует discard и сохраняет
  playback/selection/draft. Если переход меняет запись, речь, kind или report,
  существующий dirty/revision guard решает, можно ли уйти. Отказ оставляет старый
  editor, фокус и согласованные URL/selection; не добавлять history loop или новый
  entry в обработчике popstate. Hash и остальные параметры не должны теряться.
- «Перевод» включает прежние настройки/явное действие запуска и доступ к общему
  speech feed с `subtitle-mode`: original, ru, both. Режим both даёт одновременный
  оригинал и перевод тех же реплик, на узком экране — последовательно. Не клонировать
  feed/editor и не подменять режим при каждом клике; выбранный режим и речь сохраняются
   между областями. Original остаётся доступен при пустом/частичном/ошибочном переводе.
   Без `translation_url` сохраняется текущий fallback на оригинал (`create.js`);
   отсутствие результата объясняется явно, открытие области не запускает перевод.
  Экспорт original/ru и управление участниками остаются доступны в соответствующем
  контексте; выбор вкладки не меняет provider/model/settings или готовые блоки.
- «Все включённые панели» сохраняет одновременный доступ к расшифровке, настройкам
  перевода и материалам, если они включены v1. Технические сведения/параметры и
  участники имеют доступные контекстные disclosures; скрытие video/transcript не
  должно лишать доступа к ним, stop/recovery, версиям, ошибкам и reset.

## Тестовая матрица Task 7

**C** — исполняемая characterization текущего preference controller, не tabs E2E.
**S** — статический review исходников. **G** — обязательный будущий browser gate,
пока не пройден для production workspace tabs. Команда C:
`node tests/workspace_view.cjs` или
`.venv\Scripts\python.exe -m pytest -q tests/test_workspace_view.py`.

| ID | Вход / действие | Ожидаемый результат / oracle | Evidence / следующий gate |
| --- | --- | --- | --- |
| P1 | 128 масок семи flags × side/stacked | Точное чтение всех 256 сочетаний, bytes неизменны, 1 read / 0 writes | C; G: эквивалентность старого multi-panel вида и всех действий до Task 10 |
| P2 | Нет ключа; malformed/null/array; version≠1; частичный v1, wrong types, unknown fields | Defaults/merge; без eager write; explicit save сохраняет известные поля | C; G: нет flash скрытых областей |
| P3 | Default/reset, video off, оба главных off, все flags off, notes+article | Точные defaults, доступный reset; независимые hide и subtabs без смены editor | C: preference state; G: DOM, keyboard, подсказки и один iframe |
| U1 | flags=false + stage=notes/report/material=article/job/folder/#hash | Сейчас preferences URL-neutral; в будущем explicit target раскрыт без save; recording/version выбирает прежний owner | C: только neutral preferences; S: route owners; G: precedence, reload и конфликт kind/report |
| U2 | `/`, `?job=`, `/create?folder=...&stage=speech`, пустой `/create`, stage=source; unknown stage/material; недоступный report | Сохранить маршруты, no-recording flow и hash; invalid не создаёт выбор/результат; отсутствующая цель объясняется | C: unknown preference neutrality; S; G: реальные deep links и fallback |
| H1 | Local tab click; затем reload | Нет новой history entry/save; сохраняются DOM/фокус/ввод; reload по URL/v1 | 8a: локальный click/DOM/focus без history/save; G: полный URL/reload и editor input |
| H2 | Back/Forward по stage/report/material, затем другой job/folder; clean и dirty | URL/selection/область согласованы; guard отказал → старые DOM/draft/revision/Undo; нет history loop | S: текущие gaps ниже; G с quick-edit и iframe dirty, stale polling |
| F1 | getItem throws; setItem throws/quota; reset; reload | Defaults при read failure; изменения в памяти при write failure, старые bytes сохранены; reload читает старое | C; G: полноценная страница при недоступном storage, без ложного обещания save |
| F2 | storage key / key=null / чужой key, malformed/removed value | Только нужные события перечитывают без записи, invalid → defaults | C; G: активная вкладка, override и focus не теряются |
| E1 | embedded=1 | 0 storage reads/writes, нет второго workspace controller | C; G: один настоящий iframe/Undo при hide/show |
| T1 | original/ru/both; готовый/пустой/частичный/error перевод, длинные реплики | В both видны оба текста без копий; режим/речь/экспорты сохранены, нет генерации | S: существующий select; G Tasks 8/9a, original+translation на узком экране |
| M1 | Notes/article, независимые версии, empty article, dirty + Undo | Нет подстановки notes в empty article, нет reload при hide, guarded смена kind/version | Существующие material fixtures; G Task 9b, не результат прототипа |
| A1 | Mouse/Tab/Shift+Tab, Left/Right/Home/End, busy/error/stop/recovery; все размеры MASTER | Один tab-stop, видимый focus, скрытые панели недоступны, операции вне вкладок | G: production DOM/captures, zoom/forced-colors; Windows scaling/WebView2 отдельно |

### Известные gaps и граница следующего increment

- `workspace-view.js` знает локальные вкладки 8a, но не разрешает URL; C доказывает только сохранность v1.
  `studio.js` обрабатывает popstate stage/report, но это не полная guarded навигация
  по job/folder/material. `recording.js` читает material при старте/смене source и
  пишет его через replaceState, но не имеет собственного material popstate handler.
  Нельзя объявлять H2 пройденным или расширять смысл stage на перевод.
- Существующие URL writers собирают `/create?` из search и не гарантируют сохранение
  hash. Исправление потери hash и согласование guarded history нужно выделить в
  bounded slice Task 8; в Task 7 production не исправляется и baseline не меняется.
- `paintMaterialTabs()` сейчас добавляет `material=notes` даже без выбора пользователя.
  Отличить такой старый URL от явно созданного deep link невозможно. Приоритет выше
  применяется к обоим; будущий initial paint не должен добавлять отсутствующий
  material только ради визуального default. Изменение этого writer — отдельная
  проверка Task 8 с reload, конфликтующим stage и ссылками из библиотеки.
- Защита storage в C относится только к workspace preferences: `studio.js` читает
  speech-engine, а `recording.js` playback-link вне try/catch. Поэтому отказ
  localStorage всей страницы пока не проверен и может прервать эти controllers.
  Для F1 нужен отдельный bounded storage-hardening slice перед production acceptance;
  данные черновиков и другие ключи не переносить и не очищать.
- Нет старого URL для выбранной области перевода или workspace «Материалы» отдельно
  от stage/report/material. Новое URL encoding и last-tab persistence отложены:
  первый slice работает без них. Любое будущее добавление требует отдельного
  routing/storage решения, а не скрытого переиспользования stage.
- Compatibility view и временное раскрытие расшифровки подключены в 8a; URL/guard
  gaps и полная multi-panel parity остаются отдельными gates. Не удалять controls до G/P1–A1.
- Прототип Task 6 не моделирует реальный playback, iframe, revision или Undo.
  Ни эта матрица, ни Node VM не доказывают installed WebView2, Windows scaling или
  аппаратную готовность. Открытых решений по precedence/default/reset больше нет;
  перечисленные integration gates остаются непроверенными.

## Приёмка последующей реализации

- Все прежние действия, статусы, ошибки и восстановление доступны при пустом,
  активном, завершённом и ошибочном задании; выбор вкладки не создаёт задание.
- Мышь и клавиатура: один Tab-стоп в tablist, Left/Right/Home/End, видимый фокус;
  переключение не прячет фокус и не теряет незавершённую правку.
- Сохраняются один плеер и его позиция, один iframe, Undo, dirty/revision guards,
  независимые версии речи и материалов, переходы и история браузера.
- Проверены старые, частичные и неверные preferences, отказ хранения, маршруты,
  Back/Forward, узкое окно и длинные имена. Новые проверки дополняют существующие
  `tests/test_workspace_view.py` и сценарии `scripts/verify-recording-ui.py`.
- Локальные fixture-проверки не являются доказательством installed WebView2 или
  аппаратной приёмки.
