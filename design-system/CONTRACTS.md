# Сохранение поведения и контрактов

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
