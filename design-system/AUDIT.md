# UI/UX-аудит Windows Video Descriptor

19.10.2026 · baseline `9ffa842` · первый этап, до массового редизайна.

## Границы и метод

Изучены все три файла `windows-app/ui/`, общие assets create/studio/construction/speech-edit/editor/report-embed, серверные маршруты `windows-app/app.py`, `video_descriptor/serve.py`, генерация библиотеки и desktop-host. Применены `ui-ux-pro-max` и актуальные Web Interface Guidelines. Исследование эвристическое по коду; это не пользовательское тестирование. Визуальная проверка отдельного прототипа и её результаты описаны в VERIFICATION.md. Рабочая очередь, модели, Ollama, Sandbox и установленный desktop не запускались и не менялись. Существующие скриншоты в docs — исторические свидетельства, не проверка текущего runtime.

## Карта существующих экранов

| Поверхность / вход | Разметка и поведение | Сценарии и переходы |
|---|---|---|
| Desktop shell | `windows-app/DesktopHost.cs:55` | WebView2 1200×820, минимум 760×560; native «Главная», retry, трей; закрытие окна не равно остановке backend |
| Главная `/`, `/?job=` | `windows-app/ui/index.html:5`, app.js | setup по completed, новая запись, готовность, список заданий, выбранный результат; `?job=` сохраняет выбор |
| Настройка AI, inline на `/` | `index.html:7`–`:10`, app.js:15–:45, :152–:177 | диагностика → существующая папка/скачивание → inspect/connect → prepare в боковой панели → probe; Ollama, Gemini, завершение/пропуск |
| Импорт медиа | `index.html:14`, app.js:121–:133 | drag/drop или системный file picker; название, язык, устройство; raw upload → 202 → job |
| Обработка / результат | `index.html:20`, app.js:78–:119 | queued/running/done/error; видео, реплики, retry; перевод/конспект создают отдельный job; экспорт и `/create?folder=` |
| Библиотека `/output/` | `video_descriptor/library.py:87`, serve.py:161 | генерируемые карточки материалов; переход к версии; визуально третья оболочка |
| Workspace `/create?folder=&stage=&report=` | `assets/create.html`, create.js, studio.js | Источник / Речь / Конспект; версии, переименование, повтор речи, удаление, очередь; старые `/speech` перенаправляются сюда |
| Источник | create.html:20 и далее; create.js:514–:665 | второй uploader, альтернативный файл из data, общий плеер, автоследование, сведения; запускает другие сочетания параметров |
| Речь и перевод | create.html:33 и далее; create.js:44–:194, :410 | правка/разделение реплики, имена голосов, оригинал/перевод/both; provider/model, Gemini, выгрузка TXT/субтитров/перевода |
| Конспект | construction.js:21–:120; studio.js:43 | материал, провайдер, модель, стратегия, промпт, лимиты → план → запуск новой версии; варианты отчёта, OCR, диагностика |
| Редактор отчёта | serve.py:171–:204; assets/editor.js | report.html открывает `/create…stage=notes`; embedded iframe, чтение/правка, outline, Markdown, Ctrl+S, черновик, revision, dirty guard |
| Модальные окна | speech-edit.js:11; create.html в конце | реплика, подключения, удаление версии/конспекта, изображение; свои размеры/кнопки/стили |

## Основные пользовательские пути

| Путь | Последовательность | Точка риска / целевое поведение |
|---|---|---|
| Первый запуск | inline setup → папка/скачивание → проверка/подключение → prepare → probe → запись | следующий обязательный шаг расположен в другом блоке; сделать последовательную checklist, optional отдельно |
| Обычная расшифровка | файл → метаданные → устройство → upload → очередь → текст | громоздкий hero и setup выше задачи; компактная форма, состояние готовности без обязательных optional сервисов |
| Исправление | открыть job → видео/таймкод → диалог → сохранить | click-only таймкод, большой список перерисовывается; клавиатурный seek, стабильный фокус, revision сохраняется |
| Перевод | исправить текст → translate → отдельная версия → русский SRT | desktop использует selected Ollama; расширенный UI хранит отдельные настройки; явно показать провайдера/модель и область применения |
| Конспект | готовая речь → параметры/план → новый job → notes variant → правки → Markdown | два способа запуска с разными возможностями; не обещать их эквивалентность, сохранить оба до отдельной миграции |
| Восстановление | error → причина → retry → queued/running | сохранять id/кэш и запрос выбранного устройства; сетевую ошибку отделить от job.error |
| Экспорт | done → выбрать формат/язык → скачать | единая панель, сохранённый vs несохранённый текст обозначить, не менять MIME/Content-Disposition |
| Несохранённые правки | редактирование → смена версии/маршрута/выход | editor dirty/localStorage/revision и iframe guard уже есть, должны пережить новую навигацию |

## Реестр находок

P1 — функциональный/доступностный барьер или риск ошибочного действия; P2 — существенная несогласованность/дополнительная нагрузка; P3 — улучшение. Оценки — эвристика, не инциденты пользователя.

| ID | Приоритет | Место `file:line` | Наблюдение → решение |
|---|---|---|---|
| A01 | P2 | windows-app/ui/app.css:1; video_descriptor/assets/create.css:1; editor.css:1 | разные зелёный/синий акценты, 15/16 px base, ширины, тени → общие токены и opt-in классы, затем поэтапное подключение |
| A02 | P2 | windows-app/ui/index.html:7 | мастер — длинная простыня над формой; optional конкурирует с обязательным → отдельная область настроек и последовательный обязательный маршрут |
| A03 | P2 | windows-app/ui/index.html:11; app.css:1 | hero до 47 px и крупные внешние отступы отодвигают действия на окне 820 px → заголовок 28 px, короткий контекст |
| A04 | P1 | windows-app/ui/app.js:109 | `time.onclick` без button/keyboard → semantic button для перехода к времени; сохранить неизвестный end_ts, не превращать в 00:00 |
| A05 | P2 | windows-app/ui/index.html:24 | refresh «↻» без aria-label → «Обновить записи» или подписанная иконка |
| A06 | P2 | windows-app/ui/app.css:1 | focus правило охватывает только `.row button`, ссылки и поля, file input прозрачен → единый focus-visible всех controls и focus-within picker |
| A07 | P2 | windows-app/ui/index.html:14; assets/create.html:23; speech-edit.js:5 | два dropzone, нативный WAV, папка через quiet button, диалог с inline CSS → общие FilePicker/FolderPicker и Dialog; лимиты каждого контекста сохраняются |
| A08 | P1 | windows-app/ui/app.js:124–:133; assets/create.js:630–:665 | главный drop принимает ровно один файл, расширенный берёт FileList и далее первый; accept — только подсказка; главный xhr.onerror включает start без проверки readiness и не скрывает progress → единая валидация/финализация, backend остаётся авторитетом |
| A09 | P2 | windows-app/ui/app.css:1 | footnote `#7d887b` на белом ≈3.7:1, drop small `#929b90` ≈2.9:1; 10–12 px служебный текст → контрастные токены, минимум 12 px для вспомогательного |
| A10 | P2 | windows-app/ui/app.css:1 | все обычные кнопки green primary; disabled cursor wait даже при missing components → secondary по умолчанию, primary только один, причина disabled рядом |
| A11 | P1 | windows-app/ui/app.js:85–:90 | без duration/processed progress выставляется 0, нет доступного label у progress в HTML → неопределённый progress, отдельные upload/stage labels; отсутствие результата не значит 0% |
| A12 | P2 | windows-app/ui/app.js:49–:61 | одно readiness live-region полностью заменяется каждые 15 s; диагностика многословна → объявлять только существенное изменение, статус с коротким recovery |
| A13 | P2 | windows-app/ui/index.html:20 | SRT в плашке, VTT/TXT обычные ссылки; перевод/конспект конкурируют с экспортом/редактором → одинаковая панель загрузок, generation actions отдельно |
| A14 | P2 | windows-app/ui/index.html:5; assets/create.html:7 | разные headers и native «Главная»; «Материалы» и «Ваши записи» обозначают близкие сущности → единая терминология «Записи», сохранить native host |
| A15 | P1 | windows-app/ui/app.js:136; assets/studio.js:81–:85 | desktop сохраняет speech_device глобально немедленно, редактор сохраняет engine локально; наличие unsupported engine в списке не доказывает Windows capability → общий UX scope/defaults после отдельного contract-review; явно выбранное устройство не подменять |
| A16 | P2 | windows-app/ui/app.js:148; assets/create.js:153–:190 | Ollama назначения и Gemini connection редактируются разными формами/endpoint → единое представление подключений, адаптеры к текущим контрактам; никаких backend-изменений в этом этапе |
| A17 | P2 | video_descriptor/assets/speech-edit.js:11–:40 | динамический dialog без aria-labelledby, свои стили, отсутствует предупреждение при отмене набранной правки → общий dialog shell и dirty решение; сохранить edit/split/revision и поведение ошибок |
| A18 | P2 | video_descriptor/assets/create.css:14 | animation appear без reduced-motion → отключаемые движения, без анимации layout |
| A19 | P2 | windows-app/ui/app.js:73–:77, :109–:115 | список и вся расшифровка пересоздаются, список не очищается при пустом ответе → корректный empty, сохранение фокуса/scroll; длинные 50+ реплик профилировать до выбора virtualization |
| A20 | P2 | windows-app/ui/app.js:78; assets/studio.js:16–:29 | replaceState запоминает выбор, но нет обработки Back/Forward в этих модулях → спроектировать историю отдельно, сохранить query параметры при объединении |
| A21 | P2 | windows-app/ui/index.html:8 | официальный адрес Ollama представлен обычным текстом; host блокирует внешнюю навигацию → явно поддержанный «Открыть инструкцию»/копирование адреса через host policy, не простой target=_blank |
| A22 | P2 | windows-app/ui/index.html:5; app.js:137 | «Завершить приложение» рядом с обычными действиями → меню приложения; сохранить защиту 409 активных jobs и различие закрытия окна/остановки |
| A23 | P2 | video_descriptor/assets/create.html:33, :43 | настройки этапов, generation, exports, prompts расположены на одной глубине → настройки в disclosure, результат первым при done, primary зависит от этапа |

## Что уже сделано правильно и должно сохраниться

Нативные select/file/dialog; input labels в основных формах; aria-live/status для многих async сообщений; `hidden` CSS-защита; textContent для динамического текста; блокировка повторной отправки; polling выбранного id с проверкой устаревшего ответа; явный AUTO/device snapshot; отдельные postprocess версии; `revision`/conflict и draft конспекта; подтверждение удаления; tabs с Arrow/Home/End; ограничения origin/instance и WebView2 external navigation policy. Эти механизмы нельзя «упростить» при визуальном переносе.

## Решение первого этапа

Согласовать макет **Новая запись**: постоянная навигация, спокойная типографика, форма и один primary, компактная readiness, записи под формой. Reference-компоненты изолированы; production не импортирует новые CSS/JS. Дальнейшая последовательность, acceptance и rollback — в PLAN.md; карта обработчиков/API — CONTRACTS.md и machine-readable baseline.
