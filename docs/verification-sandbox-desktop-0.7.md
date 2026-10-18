# Windows Sandbox Desktop 0.7: приёмка не завершена

Дата: 19 октября 2026. **BLOCKED; acceptance_complete=false.** Установка и загрузка модели проверены, но пользовательская цепочка CPU → редактор → экспорт не выполнена. Успешную полную приёмку заявлять нельзя.

## Сборка и найденное исправление

Исходная сборка `1f622e6a7f71aa5e029e9a91313edc49aa3849d3` установилась после согласованного изменения защиты гостя, однако OpenVINO не загрузился: отсутствовал MSVCP140.dll. Это реальный дефект чистой установки. Диагностическое копирование DLL подтвердило причину, но не засчитывается как приёмка исправленной поставки.

Исправление `30f5f7146cc3fe2d00fa3c0ebf0a4b92de4b73be` включает 12 app-local DLL Microsoft VC++ 14.44.35211.0 и лицензию. Официальный подписанный redistributable, экстрактор WiX и каждый DLL закреплены SHA256; системный VC++ на хосте или госте не устанавливался. Из этого коммита заново собраны ZIP и EXE. На **второй чистой Sandbox** установлен исправленный EXE: OpenVINO/GenAI загрузились, CPU обнаружен.

Версия дистрибутива 0.7.0; health сообщает `0.7.0-prototype`, metadata Python-проекта остаётся 0.1.0. Это разные существующие поля версии, а не доказательство разных артефактов.

| Артефакт | Байты | SHA256 |
|---|---:|---|
| VideoDescriptor-0.7.0-windows-x64-setup.exe | 223640342 | `73095e95fca5990d09b3d5433caece2f57a7d1949423a770100d7c27cb690d96` |
| VideoDescriptor-0.7.0-windows-x64.zip | 265451844 | `414bb08d4f48cbae6e9c212a69a9b17d86779786a5a7cc5ddac9a22a07b13ada` |

Все 4415 файлов исправленного ZIP сверены внутри гостя с release manifest, лишних файлов нет. Версии: Python 3.12.10; OpenVINO 2026.4.1; GenAI/tokenizers 2026.4.1.0; faster-whisper 1.2.1; numpy 2.5.4; imageio-ffmpeg 0.6.0 / FFmpeg 7.1; WebView2 SDK 1.0.2903.40; Inno Setup 6.7.3. Полные исходные хеши сохранены отдельно в JSON в `runs`.

## Реальная Sandbox и ограничения защиты

Два отдельных чистых гостя: Windows 11 Enterprise 10.0.26100, WSB CLI 0.8.107.0, 8192 MiB RAM. До установки отсутствовали системный Python, Docker, предыдущая установка, пользовательский HF cache и проверяемые переменные API-ключей. WebView2 Runtime уже присутствовал (155.0.4283.45/.62); отсутствие WebView2 не проверялось. Монтировались только выделенный read-only input и writable reports. Репозиторий, домашняя папка, секреты и пользовательские модели не передавались. vGPU, clipboard, audio/video input и принтеры отключены.

**Обычная защита:** исходный неподписанный EXE блокировался Smart App Control (0x800711C7, события 3033/3077). Скриншот пользователя и Code Integrity сохранены. Исправленный EXE тоже неподписан; его запуск с исходной политикой отдельно не повторялся. Блокировка доверия не устранена добавлением DLL.

**Согласованный функциональный прогон:** пользователь явно разрешил SAC Off только в одноразовом госте и перезапуск только гостя. Изменено VerifiedAndReputablePolicyState 1 → 0, выполнен CiTool refresh и гостевой reboot. Изменение защищённого MinValueSeen было отклонено; принудительное изменение владельца/ACL не применялось. Windows Security UI в госте не открывался. Основная Windows, Defender и Firewall не изменялись. Поэтому функциональные PASS ниже относятся к гостю с изменённой политикой SAC, а не стандартной защите.

Официальные ограничения: [Smart App Control FAQ](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions), [тестирование приложения с SAC](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/test-your-app-with-smart-app-control), [конфигурация Sandbox](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file).

## Что действительно выполнено через UI

Исправленный EXE установлен интерактивно; ярлык Start Menu использован для запуска отдельного окна WebView2 с собственным embedded Python backend. В мастере доступны CPU и версии OpenVINO/GenAI, отсутствие Intel GPU/NPU отображено корректно. Проверка пустого пути модели дала понятную встроенную ошибку без traceback.

Через UI раскрыты источник, revision и размер, подтверждено согласие и выполнена настоящая загрузка `https://huggingface.co/OpenVINO/whisper-small-fp16-ov`, revision `2410d022171ca8a97343182f88eec8807a324db9`. Приложение показало проверенную подключённую модель. Независимо сверены SHA256 и размеры **18 файлов, 493208911 байт**. Модель с хоста не копировалась. После загрузки сетевой адаптер гостя отключён, что зафиксировано отдельно; последующей транскрипции не было, поэтому автономная обработка этим не доказана.

Надпись «Готово» у операции загрузки не засчитана как инициализация CPU worker. Явный выбор CPU, Prepare и сама обработка не завершены. На последнем продолжении `wsb list --raw` вернул пустой список окружений; гостевой диск уже недоступен. Причина закрытия не установлена. Сохранённые общие reports и скриншоты остались на хосте; модель и состояние гостя нельзя считать сохранёнными для продолжения.

## Проверки в настоящей Sandbox

PASS означает фактическую проверку в госте, с оговоркой SAC выше. NOT_TESTED означает отсутствие выполненного сценария; результаты CI и mocks не переносятся сюда.

| Проверка | Статус | Доказательство / ограничение |
|---|---|---|
| Запущена настоящая Windows Sandbox | PASS | CLI instance e3d0bf90-ff47-409f-a022-e414f7581a25; визуально проверен гостевой рабочий стол. |
| Нет системного Python | PASS | Get-Command python,python3,py не нашёл команд до установки. |
| Нет Docker | PASS | Get-Command docker не нашёл команд. |
| Нет предыдущей установки и пользовательского HF cache | PASS | existing_installation=false; existing_user_models=false. |
| Не унаследованы переменные API-ключей | PASS | Нет имён переменных GEMINI/API_KEY/HF_TOKEN/OPENAI/WHISPER/OLLAMA; значения секретов не читались. |
| Минимальные общие папки | PASS | Только C:\VD-Input read-only и C:\VD-Reports writable; repository/home/private folders не смонтированы. |
| Отдельный сетевой профиль с согласия пользователя | PASS | Старый профиль Networking=Disable; новый Enable согласован в чате, Ethernet Up подтверждён в госте. |
| WebView2 Runtime уже присутствует | PASS | 155.0.4283.45 и 155.0.4283.62; сценарий отсутствующего Runtime этим не проверен. |
| SHA256 и размеры EXE/ZIP | PASS | Fixed EXE/ZIP hashes and sizes verified inside the new guest; see fixed-artifact-verification.json. |
| Состав и SHA256 файлов ZIP | PASS | All 4415 packaged ZIP files checked against release manifest in the new guest; no extra entries. |
| Запуск EXE в стандартной защите гостя | BLOCKED | Original unsigned EXE blocked by guest Smart App Control (0x800711C7, Code Integrity 3033/3077). Fixed EXE is also unsigned; its default-policy launch was not independently retested. Modified-policy installation is recorded separately. |
| Установка без системного Python | PASS | Fresh rebuilt guest: interactive EXE install completed without system Python or VC++ installation, after the authorized guest-only SAC change. |
| Ярлык Start Menu | PASS | Installed Start Menu shortcut observed and used to launch the app. |
| Обычный запуск Desktop | PASS | Launched the installed Start Menu shortcut in the fresh guest. |
| Отдельное окно WebView2 без браузера | PASS | Separate desktop WebView2 window rendered the wizard; browser launch was not required. |
| Подключение к собственному Python backend | PASS | Installed embedded Python backend served the desktop UI; saved /health identifies the guest installation/workspace. |
| Локальный API и интерфейс | PASS | Wizard rendered and responded; read-only health/setup/diagnostics corroborated the UI. Main transcription flow was not exercised. |
| Скрытие в трей и восстановление | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Полное завершение приложения | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Мастер первоначальной настройки | PASS | First-run wizard rendered in the fresh installed application. |
| Обнаружение CPU в мастере | PASS | UI and OpenVINO device inventory reported CPU; OpenVINO and GenAI versions loaded successfully. |
| Корректное отображение отсутствующих GPU/NPU | PASS | UI reported no Intel GPU/NPU; diagnostics list only CPU. vGPU was disabled. |
| Отсутствие модели в UI | PASS | Initial wizard reported no Whisper model before download. |
| Предложение модели и source/revision/size | PASS | UI displayed official OpenVINO Whisper small FP16 source, pinned revision and approximately 470 MiB download. |
| Подтверждение загрузки через UI | PASS | Consent checkbox and Download button operated through the real UI. |
| Реальная загрузка официальной модели | PASS | Real download completed inside the guest from pinned Hugging Face revision; no host model copied. |
| SHA256 всех скачанных файлов модели | PASS | All 18 downloaded files independently checked for SHA256 and size against packaged component manifest; 493208911 bytes total. |
| Подключение скачанной модели | PASS | UI reported the verified model connected after download. This does not establish worker readiness. |
| Выбор CPU | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Успешная инициализация CPU worker | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Состояние Готово только после инициализации | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Выбор и загрузка настоящего тестового видео через UI | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Настоящая CPU-транскрипция видео | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Результат с сегментами речи | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Корректные таймкоды | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Открытие редактора | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Изменение и сохранение реплики | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Экспорт SRT и проверка содержимого | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Экспорт TXT и проверка содержимого | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Настоящее длинное задание продолжает работу в трее | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Результат доступен после восстановления окна | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Отсутствие Ollama/Gemini не мешает CPU | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Отсутствие скрытых запросов к облаку во время обработки | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Повторный запуск | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Сохранение настроек | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Сохранение результатов | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Установщик при работающем приложении | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Переустановка | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Удаление | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Сохранение пользовательских данных при удалении | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Понятная ошибка: backend недоступен | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Понятная ошибка: модель отсутствует | PASS | Inspecting files with an empty model path displayed an inline instruction to choose a Whisper small FP16 folder; no traceback. |
| Понятная ошибка: несовместимая модель | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Понятная ошибка: порт занят | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Понятная ошибка: сеть недоступна | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Отмена настройки пользователем | NOT_TESTED | Not executed before the guest disappeared. Final continuation found no running Sandbox. No result inferred from CI, mocks, download completion or host tests. |
| Отсутствующий WebView2 и его официальная установка | NOT_TESTED | Runtime уже присутствует; не удалялся. |
| Недостаток места через изолированный mock | NOT_TESTED | Отдельная проверка в этом прогоне не выполнялась. |
| Версионное обновление | NOT_TESTED | Подходящий подписанный upgrade artifact не подготовлен; прежний host fixture не засчитывается. |
| OCR | NOT_TESTED | Реальная зависимость не проверена. |
| Диаризация | NOT_TESTED | Реальная зависимость не проверена. |
| Аппаратное NPU-распознавание | NOT_TESTED | Устройство в госте не подтверждено; vGPU отключён. |
| Аппаратное GPU-распознавание | NOT_TESTED | Гость показывает Microsoft Remote Display Adapter; физический GPU не предоставлен. |
| Отключение сети гостя после загрузки | PASS | Guest Ethernet 2 disabled and state recorded. No subsequent recognition was run; this is not proof of offline transcription. |

## Отдельные категории

- **Основная Windows:** сборка исправленных артефактов; pytest 250 passed, 2 skipped (51.33 s); Ruff и pip check прошли. Установка приложения на основную Windows в этом прогоне не выполнялась.
- **Mocks на хосте:** unit/API suite включает несовместимые модели, прерванные загрузки, hash mismatch и чужой listener. Это не проверка ошибок через Sandbox UI. Отдельный low-disk mock в этом прогоне не выполнялся.
- **Windows CI:** [run 39170868602](https://github.com/IavnFGV/video-descriptor/actions/runs/39170868602), success для `30f5f71`: unit/API, сборка, реальный WebView2/tray smoke, детерминированный ZIP, install/running-update refusal/reinstall/upgrade fixture/uninstall на runner. Это не реальная CPU-транскрипция в Sandbox.
- **Container CI:** [run 39170868594](https://github.com/IavnFGV/video-descriptor/actions/runs/39170868594), success для того же коммита.

## Результаты речи, экспорта и оставшаяся работа

Подготовлены короткий синтетический MP4 и отдельный 180-секундный MP4 с реальной повторяющейся речью. Известный текст: “This is a local transcription test. The blue train arrives at the station at nine. Please save this sentence as subtitles.” Файлы без личных данных; хеш короткого MP4 `88e3086d22d257a4af4485287c4ca0184259408c12722f80ead0b4e4517a8b72`. Имитация задержки не использовалась.

**Результатов распознавания и экспортированных SRT/TXT нет.** Нужно заново создать чистый гостевой прогон для CPU worker, обработки, сегментов/таймкодов, редактора и экспорта; затем длинное задание в трее, повторный запуск, сохранение данных, reinstall/uninstall и отрицательные UI-сценарии. Отсутствие Ollama/Gemini отображалось в диагностике, но его независимость от CPU-обработки ещё не доказана. GPU/NPU/OCR/диаризация не проверены на реальном оборудовании/зависимостях. vGPU не был включён, NPU в госте не обнаружен.

Изменения отправлены в рабочую ветку; [draft PR #1](https://github.com/IavnFGV/video-descriptor/pull/1). Merge, tag и release не выполнялись.

Машинный отчёт: [verification-sandbox-desktop-0.7.json](verification-sandbox-desktop-0.7.json). В нём раздельные прогоны, все статусы, категории, зависимости и SHA256 каждого файла доказательств. Ключевые материалы: [fixed preflight](verification-sandbox-desktop-0.7-evidence/fixed-preflight.json), [хеши исправленного дистрибутива](verification-sandbox-desktop-0.7-evidence/fixed-artifact-verification.json), [хеши модели](verification-sandbox-desktop-0.7-evidence/model-hashes.json), [скриншот модели](verification-sandbox-desktop-0.7-evidence/model-downloaded.jpg), [исходная блокировка](verification-sandbox-desktop-0.7-evidence/smart-app-control-block.png). Временные полные логи/медиа остаются в ignored `windows-app/runtime/sandbox/acceptance-20261019{,-fixed}/`.
