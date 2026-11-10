# Сохранение поведения и контрактов

09.11.2026: Windows 0.8.34 — успешная проверка диаризации сохраняется между запусками и UI-обновлениями. Готовность привязана к модели, Python/метаданным пакетов, lock-файлу, worker и устройству/драйверу; отсутствие proof не выдаётся за готовность. При неизменных входах не запускать повторный inference и не требовать Hugging Face, токен или ручную проверку. Доступ HF показывать только для необходимой загрузки модели. Ошибка проверки сбрасывает кеш.

Обязательное правило журналирования (09.11.2026): все изменяющие API-операции автоматически проходят общий HTTP audit; worker, взаимодействие с моделью, проверка и сохранение результата вызывают video_descriptor.action_history.record — единую точку структурированной записи. Фиксировать начало, успешный результат и ошибку; сохранять operation/job/request id, этап и статус. Не писать ключи, credentials, тела запросов, промпты и расшифровку в общий журнал. Общий журнал задаётся VIDEO_DESCRIPTOR_EVENTS (Windows: application_log_directory или runtime/logs/events.jsonl), события записи — рядом с её артефактами. Общий файл находится вне переносимой папки записей, чтобы журналирование не нарушало проверку её контрольных сумм. Новый endpoint/фоновая операция проверяются на наличие событий и видимость в UI; отдельный logger вместо общего механизма не допускается. Legacy run.log/construction.log остаются диагностическими дополнениями.

Обязательное правило UI (09.11.2026): между полем и связанными с ним кнопками, а также между кнопками одной группы — 8 px (`--vd-control-gap`); между самостоятельными группами — 16 px (`--vd-group-gap`). Поле с действиями оформлять `.vd-control-group`, кнопки — `.vd-actions`. Едино для приложения, настроек, библиотеки, диалогов и отчётов; CSS собирать из общих источников. Не компенсировать отступы пробелами в HTML или отдельными случайными margin.

09.11.2026: исправление меток пакетное: «Исправить все метки» выбирает ближайшие подтверждённые начала реплик; индивидуальные замены оставляют список и отметку ожидания проверки. Проверка всего текста выполняется явно, затем сохранение; ручные правки не теряются.

09.11.2026: штатный локальный preview после merge main: post-merge запускает installer в фоне, затем Run-Dev.ps1 -Restart -Open открывает код main в браузере. Конфигурация/статус и два перезаписываемых лога — .git/local-dev; порт отдельный, records_directory общий с установленным приложением. Guard проверяет development/instance/installation/workspace; активная очередь не прерывается. Модели и системные компоненты не устанавливаются. UI показывает версию и коммит.

09.11.2026: Windows 0.8.33 — восстановление конспекта показывает все ошибки меток с разделом/строкой, точным переходом и подтверждёнными кандидатами с текстом речи. POST construction-recovery action=validate проверяет черновик без записи/запуска worker; revision guards сохранены. Замены выбирает пользователь; исходный ответ модели не меняется.

09.11.2026: Windows 0.8.32 — рядом с недоступной кнопкой генерации показана причина (активное задание, очередь, загрузка/выбор модели, отсутствие речи). Заголовок не предлагает запуск во время активного задания. Автоматическое определение контекста расположено под соответствующим полем с пояснением.

09.11.2026: Windows 0.8.31 — создание статьи открывает настройки статьи с отдельным редактируемым промптом и явной кнопкой запуска. Конспект сохраняет собственный промпт; article_prompt хранится отдельно, backend применяет его только для статьи. Выбранная расшифровка, версии и dirty guards сохранены.

08.11.2026: согласован независимый выбор версий расшифровки, конспекта и статьи. Служебные снимки сохраняются в хранилище, но скрыты в выборе расшифровки; выбор материала не переключает речь. Новые материалы используют выбранную речь, старые не изменяются. Общий редактор показывает выбранный конспект или статью; dirty guards и синхронизация по времени сохранены. Удаление адресует выбранный материал.


08.11.2026: ручное восстановление конспекта — POST /api/construction-recovery {folder} → {text,revision,anchors}; {folder,text,revision} проверяет метки и ставит существующее ошибочное задание в очередь. Диалог сохраняет текст при ошибке, подтверждает закрытие грязного черновика; beforeunload guard. Raw model response, speech ids и обычные редакторские revisions сохранены.


22.10.2026: конспект использует одну CodeMirror history для полного редактора,
локальных разделов и действий чтения. Ctrl+Z/Ctrl+Shift+Z и ↶/↷ отменяют/повторяют;
сброс несохранённых правок подтверждается и возвращает savedText. Новый раздел —
одна операция, Escape/Отмена до применения удаляет вставленный черновик. Локальная
правка раздела учитывается notesEditorDirty и beforeunload, «Применить» не пишет на диск.
Субтитры: POST /api/speech-edit action=restore принимает segments/translations только
при совпадении актуального revision, под прежним EDIT_LOCK и в пределах прежнего
лимита тела. Проверяются ID, текст, интервалы, голоса и перевод; сохранение атомарно.
Новый backend enum job не добавлен. История клиента по folder хранит до 20 действий
edit/split (без переименования реестра голосов), очищает redo при новой правке и не
переносится между документами/перезапусками. В полях ввода Ctrl+Z остаётся локальным;
на расшифровке вне ввода отменяет сохранённую правку с revision guard.

22.10.2026: единая расшифровка использует существующий enableQuickReplyEdit,
createSpeakerName/createSpeakerSelect. Live snapshot добавляет speech_edit_revision
и speaker_options из editable_result; UI отправляет реальные index/revision без
пересчёта версии. Polling не заменяет DOM при speechReplyEditing. Выбор версии/конспекта
использует mayLeaveQuickReply; Ctrl+Enter сохраняет, Escape отменяет, конфликты оставляют
введённый текст. Голос, времена и перевод сохраняют прежний API-контракт.

21.10.2026: согласованная единая страница записи в отдельной ветке.
Native выбор job ведёт непосредственно на /create?job=; старые URL сохраняются.
GET /api/recording?folder|job возвращает только варианты той же исходной записи,
их статусы, названия моделей, точную папку снимка речи и активное задание; без ключей.
Списки результатов независимы, выбор конспекта выбирает его сохранённую речь.
В DOM один process-video: положение и выбор варианта не заменяют его и не сбрасывают
время при неизменном source. Магнитик — независимый playback-link; follow остаётся
отдельным следованием обработке. Таймкоды идут через recordingUI.seek; wheel/touch
приостанавливают прокрутку до явного возврата. Dirty guard конспекта сохраняется
также перед новым запуском. Native POST /api/speech-run закрепляет make_plan для
существующего источника, speech_only=true, отклоняет параллельный запуск той же
записи; Origin/Host и storage guards сохранены. Native notes используют прежний
postprocess с instance header, construction snapshot и cloud_confirmed, лимит JSON
расширен до 400000 байт для существующего редактируемого промпта.

Финальный перенос 19.10.2026: migrations/main.json разрешает точные UI-модули,
HTML-generators library/report и единственное дополнение static asset allowlist.
Baseline SHA не менялись. Guard теперь проверяет также исходные workspace IDs,
JS API literals и назначения обработчиков каждого мигрированного модуля.
Новые SRT-ссылки вызывают прежний /api/subtitles. HTML собирается локально из
текущего Markdown через существующий DOMPurify; серверных форматов не меняет.


Обновление 19.10.2026: согласованная главная внедрена. Номера строк ниже относятся к исходному baseline. `migrations/main.json` явно разрешает три UI-пути; guard проверяет сохранение ids/handlers/API literals и неизменность backend/host/assets редактора. Baseline SHA не обновлялись. Runtime-проверки: IMPLEMENTATION.md.

Baseline `9ffa842`. `baseline.json` содержит SHA256 исходников, все статические DOM ids и прямые `$('<id>')` ссылки desktop app.js, все строковые API endpoints в JS. Динамические пути и generated controls дополнены ниже. `python scripts/check-ui-audit.py` сверяет baseline с рабочим деревом. На первом этапе рабочие HTML/CSS/JS, Python API и host неизменны (нормализация только CRLF → LF). Это доказательство отсутствия регрессии от текущих изменений, **не** E2E-проверка существующего продукта.

## Desktop обработчики

| IDs / событие | Обработчик, запрос | Инвариант |
|---|---|---|
| file change; drop drag/drop | app.js:121–:124 | один File, не строка пути, одинаковые ограничения 4 GiB |
| upload submit, start | app.js:125–:133 → POST `/api/upload?filename=&title=&mode=audio&engine=whisper-local&device=&speech_only=true&language=` raw File | XMLHttpRequest upload progress; только 202 успех; ответ id; не менять engine на редакторский |
| speech-device change | :136 → POST `/api/compute-settings` `{speech_device}` | AUTO/NPU/GPU/CPU, применяется к новым jobs; availability ≠ ready |
| jobs row; refresh | :73–:78, :138 → GET `/api/jobs`, GET `/api/speech?job=` | `selected`, `?job`, polling 2 s при active; 5 s после сети; stale-id guard |
| retry | :134 → POST `/api/retry?id=` | сохранить id/cache, не создавать повтор upload |
| start-npu | :135 → POST `/api/native/prepare` | instance header, без скачивания, capability проверки backend |
| stop | :137 → POST `/api/native/stop` | instance header; 409 при queued/running, не останавливать сервисы обходным путём |
| translate-run / notes-run | :139–:145 → POST `/api/native/postprocess` `{folder,task:translate|notes}` | instance; selected Ollama; отдельная версия из исправленной речи; не заменять `/api/notes-run` |
| setup-open / setup-toggle / setup-finish | :146, :160–:161 → POST `/api/setup/complete` | completed не означает verified; повторное открытие доступно |
| pick-model / inspect-model / setup-form | :30–:37, :149–:151 → POST `/api/setup/pick-model`, `/inspect`, `/model` | path; отмена picker не стирает поле; inspect не подключает; Windows native folder dialog |
| diagnostics-refresh | :162 → POST `/api/setup/refresh`, GET `/api/setup/diagnostics`, `/api/doctor` | обновление hardware/backend readiness, не только наличие устройства |
| download-model | :163 → POST `/api/setup/download` `{confirmed:checkbox}` | источник/revision/bytes + явное согласие; без silent download |
| probe-model / probe-custom | :164–:175 → POST `/api/setup/probe` | builtin JSON или raw WAV `audio/wav`; custom до 500000 bytes; формат/длительность проверяет backend |
| ollama-refresh / ollama-form | :40–:45, :147–:148 → GET/POST `/api/setup/ollama` `{model,task}` | только установленная модель; translation и notes назначения; не обещать проверенную генерацию |
| gemini-form / gemini-check | :176–:177 → POST `/api/setup/gemini` | save `{api_key,model,billing_mode,free_ack}` или `{check:true}`; пустой ключ сохраняет прежний, введённый очищается |
| srt/vtt/txt/ru-srt/editor/open-report | :100–:106 | оригинал/ru + format; encoded folder; downloads после job+result done; report redirect сохраняется |
| динамический time / edit | :109–:110 → `editSpeechReply(result,index,video,onSave)` | index и segment.id не смешивать; onSave перерисовывает сохранённый ответ |

Запросы setup/prepare/stop/native postprocess сохраняют `X-App-Instance`, полученный `/health`. JSON и raw upload имеют разные Content-Type. Промежуточные ошибки API содержат `error`, не 200 fake success. Refresh/readiness polling не должны стирать фокус и ввод.

## Workspace /create и общие модули

| Функция | Данные / события | Нельзя потерять |
|---|---|---|
| Навигация studio.js | query `job`, `folder`, `stage`, `report`; tabs source/speech/notes; `window.studioUI` | aria tabs и keyboard, dirty guard report iframe, reportVariant/resetReport/refreshReport |
| Источник create.js | GET `/api/speech-inventory`, `/api/runs`; POST `/api/speech-run` существующий video или POST `/api/upload` File | альтернативный источник data и версионность; media options; параметры зависят от текущего speech/construction выбора |
| Результат | GET `/api/job?id=`, `/api/progress?job|folder`, `/api/request`; construction-ready/started | selected snapshot, previous_report_url во время нового notes, video sync/follow, translation blocks |
| Правка speech-edit.js | POST `/api/speech-edit` `{folder,revision,index,action,text,speaker,translation}` + `start,end` при edit; `at,right_text,right_speaker,right_translation` при split | optimistic concurrency; граница внутри интервала; переводы переносятся вручную; ошибки оставляют dialog открытым |
| Имена / повтор речи | POST `/api/speech-names` `{folder,speaker_names}`; `/api/speech-run` `{video,title,engine,mode:audio,speech_only:true}` | старые результаты сохраняются, speaker ids стабильны |
| Перевод / подключения | GET/POST `/api/translation-settings`; GET `/api/gemini-models` | ключ не возвращается клиенту; free_ack/billing; изменения следующих блоков не переписывают готовые |
| Construction | GET/POST `/api/construction-settings`; GET `/api/construction-models?provider=`; POST `/api/construction-plan`, `/api/notes-run` `{folder,settings}` | input/material/provider/model/strategy/grouping/context_tokens/output_tokens/chunk_seconds/max_chunk_seconds/max_chunk_chars/prompt; numeric типы; plan version stale guard; construction-settings-snapshot |
| Вспомогательные параметры | GET/POST `/api/prompts` `{task,text}`; POST `/api/thinking?folder=` | промпты и thinking применяются к следующим запросам, не текущему |
| Удаление | POST `/api/delete-version`, `/api/delete-notes` | подтверждение, busy запрет, исходный файл и другие версии сохраняются |
| Редактор notes | относительные GET/POST `editor.json` `{text,revision}` и `title.json` `{title}` | edit conflict, notes.user.md, Ctrl+S, draft key/recovery, beforeunload и `notesEditorDirty`, сохранение не равно скачивание |
| Export | `/api/subtitles?folder=&language=original|ru&format=srt|vtt`; `/api/transcript-text?folder=`; construction-download; Markdown Blob из editor | actual MIME/filename, язык, revision, таймкоды и id; неизвестный end_ts=-1 не выдумывать |

## Состояния и представление

| Модель | Состояния | Представление |
|---|---|---|
| Job | queued → running → done или error; retry снова активирует обработку | «В очереди» / этап / «Готово» / ошибка + восстановление; никакого нового persisted enum |
| Speech result | absent / partial / status=done; segments может быть [] | done job **и** done result для export; no_speech отдельное корректное пустое состояние |
| Postprocess | job.mode=postprocess/notes; stage queued/notes/translation/done | неопределённый progress при active; исходник и отдельная версия |
| Setup operation | running/done/error, bytes/total/result | progress determinate только при total; ошибки отдельно от job; polling 1 s |
| Compute | available, ready, preparing, operation, error, requested/selected | capability отдельно от выбранного устройства; явный выбор без silent fallback |
| Editing | clean/dirty/saving/conflict/offline draft | конфликт не стирает ввод; переход не уничтожает черновик |

Никакие из предложенных UI-состояний empty/uploading/offline/invalid не добавляются в backend job.status. Они локальные presentation states.

## Матрица будущей приёмки

Каждый затронутый компонент проверять: mouse + keyboard; пусто/очень длинное имя; cancelled picker; 1 и несколько dropped files; invalid format/size; upload interruption; duplicate submit; queued/running/partial/done/error/no_speech; selected stale response; AUTO и недоступный явный device; setup consent + отмена папки; edit/split/409 revision; notes dirty navigation + разные варианты; SRT/VTT/TXT original/ru и Markdown draft; 409 stop busy. Запускать с подменённым HTTP в изолированной копии, затем существующие backend тесты с временными workspace. Аппаратные и Sandbox проверки отдельны и здесь не заявляются.

Остановка обработки (20.10.2026): добавлены stop-job и POST /api/native/cancel?id= с проверкой экземпляра. Исходные API и handlers сохраняются. cancelled=true отображается как «Остановлено»; сохранённые сегменты остаются доступными.

20.10.2026: new-record-open ведёт на #new. Форма upload сохраняет IDs, File и параметры в DOM при смене экрана. records-open возвращает список, выбранная запись открывается через ?job=. Обработка и polling продолжаются при открытии формы.

20.10.2026: inline speaker select использует прежний /api/speech-edit action=edit с edit_revision. Текст, времена и перевод сохраняются; busy блокирует параллельную правку, ошибка возвращает прежний выбор и показывается рядом.

20.10.2026: имя говорящего — кнопка с inline input; Enter/blur сохраняет speaker_names через существующий /api/speech-names, Escape отменяет ввод. Speaker id не меняется, новое имя применяется ко всем его репликам. Выбор speaker отдельной реплики остаётся справа рядом с карандашом, время слева.

20.10.2026: плюс с микрофоном создаёт уникальный speaker ID в speaker_names текущей записи через существующий /api/speech-names. Имена реестра доступны в speaker_options и допустимы для правки реплик. Добавление не переназначает реплики автоматически.

20.10.2026: обе части диалога правки позволяют добавить говорящего. Новые ID и имена остаются черновиком до сохранения; отмена учитывает dirty guard. Inline controls сгруппированы flex-контейнером без влияния на поток текста реплики.

20.10.2026: Ctrl+наведение открывает локальную quick edit форму текста реплики. Существующий /api/speech-edit с edit_revision сохраняет текст без изменения speaker/timing/translation. Ctrl+Enter сохраняет, Escape/Отмена закрывает без изменений; ошибки сохраняют введённый текст, переход к другой записи учитывает dirty state.

20.10.2026: AI Component Manager adds GET/POST /api/components with existing X-App-Instance and Origin guards. POST component=whisper|ollama|diarization, action=install|check|pull|cancel|remove; install/pull/remove require confirmed=true. Existing setup endpoints/ids/handlers remain. HF links use POST /api/setup/external with fixed terms|tokens allowlist. Operations persist separately from job enums; bytes/total are real, cancellation retains verified cache. No credentials in GET responses. Standard Whisper download/probe controls now run the unified manager; custom WAV API remains.

20.10.2026, PR #5: Ollama modes existing/service/managed, explicit connect and start_existing actions on /api/components; managed install additionally requires mode=managed. Read-only /api/setup/ollama?discover=1 probes 11434 without changing selection. Selected endpoint, ownership, version and models are visible; polling preserves mode/URL drafts. External check/pull never install, launch, stop or switch endpoints. Notes and translation snapshot one selected endpoint, including actual context checks.


21.10.2026: однократная подготовка — top-level выбор функций/устройств и один submit после общего download consent; для community-1 отдельное HF consent. POST /api/components action=prepare_selected|cancel_selected; существующие операции/IDs сохранены. Главное окно подсвечивает настройки без принудительного перехода; общий прогресс доступен после ухода/возврата. Ошибка шага не отменяет готовые компоненты.


21.10.2026: прогресс подготовки имеет текстовую подпись и aria-describedby. Процент относится к текущему файлу/этапу с реальным знаменателем. Неопределённая полоса подписана; рядом длительность subprocess и давность фактического вывода. После 60 с тишины показывается отсутствие новых сообщений и факт запуска процесса, без заявления о зависании.


21.10.2026: хранение — GET /api/storage возвращает текущие независимые roots и прогресс; POST /api/setup/storage (instance/Origin guards) action=pick|transfer|cleanup. Перенос выполняется в фоне только без активных jobs/подготовки, с leases worker/components, в пустую непересекающуюся локальную папку. Старые данные сохраняются до явной очистки после полного перезапуска; config публикуется атомарно после SHA256 и исправления путей/venv. records_directory переопределяет workspace; стандартный runtime/workspace и LOCALAPPDATA/VideoDescriptor/ai-components сохраняются по умолчанию. Пока выполняется перенос или ожидается перезапуск, мутации HTTP заблокированы; остановка во время копирования запрещена. Внешняя Ollama не переносится и не останавливается. Очистка проверяет маркеры, набор файлов и хеши; новые/изменённые исходные файлы не удаляются.


21.10.2026: перед конспектом native dialog выбирает Ollama/Gemini, модель, strategy, context_tokens и translate_after. POST /api/native/postprocess принимает construction; cloud_confirmed=true обязателен для Gemini, API-ключ остаётся в защищённых настройках. Provider/model закрепляются в job, глобальные настройки не меняются. GET /api/translation-settings возвращает только public preferences. /api/speech дополнительно возвращает progress из progress.json: phase, completed/total, chunk, request_state, received. Последовательные части конспекта получают ограниченную выдержку предыдущей части и недавние заголовки; план учитывает резерв памяти. Cache key включает эту память, поэтому возобновление восстанавливает тот же контекст из сохранённых ответов. Объединение — отдельный этап, процент показывается только для текущего этапа.


21.10.2026: auto_context=true выбирает реальный лимит модели, false сохраняет ручной context_tokens. Старые конфигурации с явным context_tokens без флага остаются ручными. Для Gemini strategy=auto|whole планируется по countTokens полного payload (включая system prompt), с резервом ответа и 1024 токена; результат переиспользуется при генерации без повторного countTokens. Если помещается, один блок и один generateContent, без consolidation. Байтовая оценка применяется к локальным моделям и безопасному разбиению. Ручное strategy=chunks сохраняется. Локальная обработка целиком ограничивает num_ctx фактически нужным размером, не выделяя максимальный KV cache без необходимости.


21.10.2026: report-embed.js делегирует клики по button[data-time] к существующему window.seekTo общего плеера. Это восстанавливает кнопки динамического Markdown-превью после удаления inline report scripts при embedded=1, включая повторный рендер после правок. Самостоятельный отчёт и оглавление сохраняют прежние обработчики.

07.11.2026: createSpeakerSelect compact=true в unified workspace скрывает отдельное добавление и включает пункт создания с назначением текущей реплике через прежние /api/speech-names и /api/speech-edit revision. Глобальное переименование остаётся в speaker-names-form; createSpeakerName сохранён для прежних поверхностей. API и dirty guards не меняются.

07.11.2026: unified recording action устанавливает actionPending до POST /api/native/postprocess, показывает aria-busy и явный статус запуска, блокирует повтор до ответа и выводит ошибку в отдельном recording-action-status (vd-error), не перезаписываемом polling списка вариантов. Backend guard, API и состояния job сохранены.

07.11.2026: диаризация публикует diarization_progress {stage,label,completed?,total?,updated_at,stage_started_at} из реальных hooks pyannote. Parent сохраняет структуру в speech.json и live snapshot. На экране один текущий этап с SVG-кольцом: unknown total — вращение без aria-valuenow, известный положительный total — измеренный процент; при reduced-motion вращения нет. Длительность этапа и давность последнего события не объявляются ETA/heartbeat модели. Стандартная линейная полоса скрыта только на активной диаризации; завершение/ошибка убирают кольцо. Unique speaker counts до clustering не показываются.

07.11.2026: construction-model — native select с автоматическим /api/construction-models?provider=. Исходные IDs и API сохранены; construction-models datalist остаётся совместимым скрытым inventory. Refresh рядом с полем, модель не переключается молча. Список провайдера проверяется перед Save/Run; stale-response guard modelRequest, недоступная сохранённая модель показана и блокирует запуск. Черновик model сохраняется до асинхронного inventory.

07.11.2026: error/cancelled различаются в presentation и recording inventory; error alert и явный retry находятся вне disclosure. Старые notes failures используют construction-error.json через live.construction_error; новые job.error сохраняют конкретную причину из этого файла. Retry вызывает прежний /api/retry, учитывает dirty guards и не запускается автоматически. parsed_notes допускает ### [start - end] как формат заголовка, проверяя обе границы по start/end исходных реплик и прежние ограничения ссылок/хронологии. Исходный Markdown и неизвестные end_ts не изменяются.

07.11.2026: пользователь согласовал терминологию «Участники» и действие «Разделить по участникам». Это текстовые изменения интерфейса/статусов и новых имён по умолчанию; speaker IDs, сохранённые имена, API и алгоритм неизменны.


07.11.2026: исправлены счётчики перевода: worker сохраняет точный translation-plan.json с source_ids и диапазонами исходных блоков; live использует этот план, для старых запусков — фактические completed/total без выдуманного разбиения. Алгоритм перевода и кэш не меняются. Панель расшифровки компактно группирует просмотр, историю и экспорт; текст можно свернуть, действие перевода находится в разделе «Перевод». Встроенный конспект занимает ширину панели и позволяет вручную менять высоту панели; прокрутка синхронизируется с видео; standalone и guards сохранены.

07.11.2026: в заголовках конспекта компактный таймкод без рамки заменяет крупную кнопку ▶; заголовок остаётся текстом, переход по времени и Ctrl-правка раздела сохранены. Для встроенного конспекта исключение из 76ch согласовано владельцем: текст использует всю ширину панели.


07.11.2026: добавлено действие «Создать статью» по полной исправленной расшифровке. Один запрос выбранной модели, отдельный результат с подписью «Статья», общий редактор и экспорт текущего текста в Markdown/HTML; существующие конспекты не заменяются. Нет выбора длины и автоматического перевода реплик. Backend закрепляет result_kind=article, input=speech, strategy=whole и инструкцию статьи; превышение контекста останавливает запуск без обрезания или скрытого разбиения. Многошаговая статья из длинной лекции отложена: https://github.com/IavnFGV/video-descriptor/issues/9.


07.11.2026: по просьбе владельца «Материал модели» убран из основной панели встроенного редактора. «Оригинальный ответ модели» находится в «Действия с конспектом» рядом с удалением; основные режимы — чтение и редактирование. Используется прежний переключатель model внутри iframe, без перезагрузки и потери несохранённых правок. Standalone отчёт сохраняет прямой доступ под новым названием.

08.11.2026: verify_release.py adds flushed progress reporting only; extraction retains the exact ZIP manifest check, SHA256 assertions and isolated smoke lifecycle. Hardware and installer tests remain explicit opt-ins. Original UI baseline is unchanged; file-specific review recorded in migrations/main.json.

08.11.2026: owner-requested self-cleaning build/verification scratch, success and failure. Temporary nested logs are disposable; final JSON and published packages remain outside scratch. Release version 0.8.28; no UI handler or API change.

08.11.2026: owner clarified full installer with cached unchanged work, not an update-only installer. CachedComponents installer branch preserves original application AppId, process identity/consent guard and settings; complete offline component archive is native-extracted only when needed. Existing noncached branch remains supported. Status labels identify cached full profile; original UI handler/API baseline retained.


09.11.2026: по запросу владельца добавлен LM Studio в существующие provider selects и отдельные поля подключения (local URL/model/optional password token). Основные IDs, handlers, routes, revision/dirty guards сохранены; desktop использует существующий `/api/construction-models?provider=lmstudio`. Список моделей — только проверка доступности сервера, генерация проверяется при обработке. Контекст/устройство загружаемой модели настраиваются в LM Studio; авто-контекст требует метаданных фактически загруженного instance. Новых CSS и массовой миграции интерфейса нет.

09.11.2026: readonly footer показывает version + номер билда из BUILD. Существующие handlers, API routes, revision/dirty guards сохранены; в health/doctor добавлено числовое поле build без новых endpoints.

## Вкладки материала — 10.11.2026

Owner-requested Конспект/Статья: additive material-tab-notes/material-tab-article и
material-panel; все прежние IDs/API остаются. Выбор версии независим от выбранной речи;
dirty editor блокирует переход и сохраняет DOM/frame/Undo/revision. Пустой explicit
independent report не подменяется snapshot report другого kind. Вкладки не вызывают
генерацию; create actions используют прежние construction handlers. Keyboard и
responsive browser regressions: scripts/verify-recording-ui.py --material-tabs-only
и --material-tabs-empty; старый release UI harness также проверяется локально.
