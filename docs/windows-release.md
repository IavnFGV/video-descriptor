# Windows: ZIP, installer и проверки

Текущие BUILD/теги/публикация описаны только в
[процедуре выпуска](development/releases.md). Версия Windows берётся из
`windows-app/release-inputs.json`, номер — из `BUILD`; версия Python-пакета
в `pyproject.toml` независима. Результаты 0.4–0.7 ниже сохранены как история.

Пакет предназначен для Windows x64; целевой desktop-сценарий — Windows 11.
Добавлены WinForms EXE, pinned WebView2 SDK и трей. Установщик проверяет WebView2 Runtime
через официальный loader API и наличие файлов обнаруженной версии. При отсутствии
Runtime скачивает официальный x64 Fixed Version CAB с Microsoft, проверяет закреплённый
SHA256 и действительную подпись Microsoft Corporation, распаковывает в
`windows-app/webview2-runtime` внутри выбранной папки приложения. Затем повторяет проверку;
ошибка загрузки, подписи или установки останавливает установку приложения с указанием
журнала `VideoDescriptor-WebView2.jsonl` в каталоге временных файлов setup.
Запись в реестре без файлов нужной версии не считается установленным компонентом.
Если Runtime уже доступен, загрузки и установки нет. Для ZIP Runtime нужен отдельно.
Fixed Runtime не меняет системную установку, реестр или ACL; desktop host передаёт
его папку в `CoreWebView2Environment.CreateAsync`. Версия 155.0.4283.62, загрузка
310492238 байт (около 296 MiB); она обновляется с новыми поставками приложения,
а не механизмом Evergreen. При обновлении пакета необходимо пересматривать закреплённую
версию и SHA256 в `WebView2Runtime.iss`. Проверяемая целевая ОС — Windows 11.
Подробности в [документации Microsoft](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution).
Проверки нового поведения и их ограничения записываются в отчёте Sandbox 0.7.
[Проверки desktop и ограничения](desktop-windows.md). Исторические результаты ниже
относятся к указанным версиям 0.4–0.6. Они не подтверждают приёмку нынешнего пакета.
Границы лицензирования и подписи: [THIRD-PARTY](../windows-app/THIRD-PARTY.md).

## Историческая приёмка 0.4–0.7 и состав пакета

Проверка 0.7 от 18.10.2026 на существующем Windows host: 4402 файла ZIP по manifest,
встроенный Python без системного Python в PATH, реальный WebView2 EXE/close-to-tray/
повторный запуск/error/retry; install/reinstall, отказ занятого upgrade, upgrade fixture
0.7.1 и uninstall с сохранением данных/настроек. Повторная упаковка одинакового payload
дала тот же ZIP SHA256. [Отчёт с SHA256 и границами проверки](verification-desktop.json).
Это не чистая VM и не новый аппаратный ASR-прогон; публичный Release не создавался.

- ZIP содержит приложение, CPython embeddable 3.12.10, закреплённые Python-библиотеки,
  OpenVINO/GenAI и FFmpeg. Python, Docker, WSL и pip на целевой машине для запуска не нужны.
- Whisper IR/Qwen/pyannote, пользовательские видео, история, `.env`, Git и локальные ключи
  исключены явным списком исходников. Небольшой Silero VAD ONNX входит в faster-whisper.
- Распакуйте ZIP и откройте `Open Video Descriptor.cmd` либо запустите `*-setup.exe`.
  Installer устанавливает только для текущего пользователя, без admin и изменения PATH.
- Установщик создаёт пункт Start Menu; ярлык Desktop — отдельная необязательная галочка.
- В 0.5 веса Whisper подключаются через «Настроить модель», модель перевода — через
  «Перевод через Ollama». Прямой config.local.json остаётся дополнительным способом.
  Скачивания весов/драйверов при установке нет.
  Без модели интерфейс работает, но распознавание показывает недоступность.

0.6 добавляет запуск конспекта и перевода из основной страницы через отдельную очередь.
Проверочный скрипт для 0.6 использует тот же native/postprocess API без ручного запуска CLI.
Гостевой блок Application Control из 0.5 пока не устранён; успешный Sandbox 0.6 не заявляется.

Проверка 0.6: [реальный UI](verification-postprocess-ui.json),
[ZIP → CPU → очередь конспекта/перевода → русский SRT](verification-language-workflow-0.6.json).
Проверено 4389 файлов, 20 s MP4; весь сценарий через postprocess API прошёл за 32.72 s
после запуска приложения с уже прогретой Ollama. Это проверка работоспособности.
ZIP: `ad44783a4f0b0307497117c88466a413879d1b9b1d8d8f06067e298346753c10`;
EXE: `db4eccd97a2224350284fbbcf9e325b73a18bd082d5b1f87dbff4be44e65687d`.
Installer 0.6 собран; отдельный lifecycle-прогон для него пока не повторён.
Успешные install/reinstall/upgrade/uninstall ниже относятся к 0.5.

Разделы ниже с результатами 0.4 относятся к сохранённым старым artifacts. Новые
проверки 0.5 записываются отдельно; наличие новых исходников не доказывает прогон CI.
Реальная opt-in проверка полного speech-only пути на хосте:

```powershell
.venv-windows\Scripts\python.exe windows-app/verify_language_workflow.py dist/VideoDescriptor-0.5.0-windows-x64.zip --video D:/samples/short.mp4 --model D:/AI/models/OpenVINO-whisper-small-fp16-ov --output dist/verification-language-workflow.json
```

Нужны уже установленные Whisper/Ollama/Qwen, без автоматических скачиваний.
Проверка создаёт временный workspace и не изменяет существующие результаты.

## Фактические результаты 0.5 от 18.10.2026

- ZIP 264243699 байт, EXE 222633812 байт. SHA256 ZIP:
  `cdaee34a6ba6006a144244ce5572cbc99cf681244e07a64bc307629fca45ff7f`;
  EXE: `159decfbdc4a7d92142e2e9547bfcd26083525c083424075b8336bcf35b57b8a`.
- Две независимые сборки ZIP дали одинаковую SHA256; проверено 4388 файлов payload.
- Полный speech-only сценарий на хосте из распакованного ZIP прошёл: 20 s MP4, CPU,
  новая версия конспекта и перевод Qwen 3.5 9B, report/chapters и русский SRT.
  49.23 s после запуска приложения включают подготовку CPU; Ollama уже прогрета.
  Это проверка работоспособности, не сравнительный benchmark.
  [Машинный результат](verification-language-workflow.json).
- Новый гостевой Sandbox-прогон **не прошёл**: Code Integrity 3033/3077 заблокировал
  native psutil/charset_normalizer при portable doctor до install lifecycle.
  DLL psutil побайтно та же, что в ранее прошедшей 0.4; причина изменения применения
  гостевой политики не установлена. Политика не отключалась и не обходилась.
  [Доказательство и точные границы](verification-sandbox-0.5.json).
- Hosted CI не запускался; новая сборка остаётся частным unsigned preview.
- На хосте отдельно прошли install/reinstall, отказ замены занятой установки,
  upgrade fixture 0.5.0 → 0.5.1 и uninstall с сохранением config и тестовых данных.
  Это не чистая VM и не аппаратный тест установленного EXE.
  [Отчёт lifecycle](verification-release-0.5.json), [сводка поставки](verification-package-0.5.json).

Пример конфигурации после распаковки/установки:

```json
{
  "whisper_model_directory": "D:/AI/models/OpenVINO-whisper-small-fp16-ov"
}
```

В дистрибутиве CPU/GPU используют `python/python.exe`. Если оригинальный benchmark NPU
уже установлен, его service/runtime сохраняется. Без benchmark доступен наш NPU adapter
с `STATIC_PIPELINE=True`, теми же FP16 small/beam 1 и внешними весами. Его доступность
зависит от модели и драйвера. Самостоятельный bundled NPU adapter прошёл реальную
контрольную пробу 20 s WAV; проверки NPU версии 0.3 использовали существующий внешний сервис.

По умолчанию workspace лежит в `windows-app/runtime/workspace`; выбранный
`records_directory` может находиться вне установки. Installer не
включает этот каталог и `config.local.json` в свою таблицу устанавливаемых файлов.
Повторная установка/обновление и uninstall сохраняют данные/настройки. Удаление данных
не выполняется скрытым скриптом. Исторические материалы WSL/benchmark не импортируются.

Перед upgrade/uninstall нужно закрыть именно эту копию и её workers. Lifecycle check
проверяет процессы из её каталога и отказывает при занятости, не убивая процессы.
Внешние NPU/Ollama этим guard не останавливаются. Проверка обновлений лишь уведомляет
и открывает страницу релиза; автоматической установки/rollback нет.

## Сборка

После проверки чистой Sandbox 19.10.2026 builder также поставляет Microsoft C++ Runtime
app-local: Python embed не содержит MSVCP140.dll, необходимой OpenVINO. Точный Microsoft
redistributable 14.44.35211.0, WiX 6.0.2 для извлечения, SHA256 каждой x64 DLL и лицензии
закреплены в release-inputs.json. Извлечение использует существующий .NET 8+ на build host
и системный expand.exe; установка VC++ на build host или целевую Windows не выполняется.
Все включённые DLL/лицензия попадают в release manifest. Для ZIP WebView2 нужен
отдельно, installer подготавливает его при отсутствии, как описано выше.
Историческая проверка — в verification-sandbox-desktop-0.7.md;
наличие исправления в исходниках само по себе не подтверждает успешный гостевой прогон.

```powershell
$compiler = & ./windows-app/Prepare-BuildTools.ps1
powershell -NoProfile -File windows-app/Prepare-Desktop.ps1
./.venv-windows/Scripts/python.exe -X utf8 windows-app/build_release.py --iscc $compiler
```

Build tool устанавливается только в `windows-app/runtime/build-cache/inno-6.7.3` для
текущего пользователя. Скачать compiler/Python можно только по URL и SHA256 из
`release-inputs.json`; дополнительно проверяется Authenticode издателя Inno Setup.
Системные драйверы, Python и Docker не устанавливаются. Используемый compiler —
[Inno Setup 6.7.3](https://jrsoftware.org/isdl.php), runtime — официальный
[Python embeddable](https://docs.python.org/3.12/using/windows.html#windows-embeddable).

`requirements-release.txt` содержит точные версии без pytest/ruff. `release-wheels.json`
фиксирует имена и SHA256 wheel inputs. Сборка проверяет соответствие pins/metadata,
игнорирует старые посторонние wheel в cache и отказывается при checksum mismatch,
неоднозначном build, traversal или пересекающемся несовпадающем payload.
Обновление wheel lock возможно только отдельным явным `--refresh-lock` с review diff.

Результаты без `--build-qualified` — `dist/VideoDescriptor-X.Y.Z-windows-x64.zip`,
соответствующий `*-setup.exe` и `SHA256SUMS.json`; X.Y.Z берётся из release inputs.
Для публичной приёмки используется `--build-qualified` и суффикс `-build.N`.
В каждом пакете `release-manifest.json` содержит hash/size каждого
файла и входных runtime/wheel. Notices/лицензии wheel сохранены в `.dist-info`.
Это inventory, не полный проверенный SPDX SBOM и не завершённый third-party legal bundle.
Проверка GPL/source obligations FFmpeg, лицензии собственного кода, notices и подписи
не заменяется наличием manifest или успешной сборкой.

ZIP использует сортировку файлов, фиксированные timestamp/permissions и одинаковый deflate.
Два запуска на одинаковых inputs должны дать одинаковые байты, что проверяется отдельно.
Это обещание воспроизводимости ZIP в закреплённом runtime; побитовая воспроизводимость
EXE и будущей Authenticode-подписи не заявлена. Manifest позволяет сравнить payload.

## Проверки

```powershell
./.venv-windows/Scripts/python.exe -X utf8 windows-app/verify_release.py `
  dist/VideoDescriptor-0.9.4-windows-x64.zip `
  --installer dist/VideoDescriptor-0.9.4-windows-x64-setup.exe `
  --iscc windows-app/runtime/build-cache/inno-6.7.3/ISCC.exe
```

Подставьте реально собранные ZIP/EXE одной версии; для build-qualified файлов
используйте их точные имена. Проверка создаёт отдельные временные каталоги с пробелами/кириллицей и реальные
тестовые установки. Проверяет hash файлов, запуск с PATH без Python, отсутствие модели,
loopback UI/doctor, graceful stop, запрет обновления работающей копии, reinstall,
upgrade fixture и uninstall с сохранением sentinel/config.
Fixture меняет installer version, а не объявляет новый выпуск приложения.
Тест не переустанавливает рабочую копию из `E:/LocalAI/video desriptor`.

Дополнительные `--video <short.mp4> --model <existing IR folder>` явно включают реальные
CPU/GPU ASR прогоны в распакованной копии на отдельных портах; по окончании завершаются
только workers этой копии с совпадением PID creation time и пути executable.
Веса не скачиваются. Это отдельная аппаратная проверка, не часть headless CI.

## CI и границы доказательств

`ci.yml` выполняет Fast и условные Windows smoke, а `windows-release.yml` вызывает
Full Acceptance с `windows_only=true`, затем публикует принятые artifacts без
пересборки. Prepare/publish имеют ограниченные write permissions; обычные проверки —
read-only. Полная матрица событий, fixture LLM и сроки хранения:
[CI policy](ci-policy.md). Не запускайте release workflow ради проверки документации.

Локальный запуск на существующей Windows проверяет работу артефактов в отдельных каталогах.
Он не доказывает запуск на чистой Windows без установленных VC/runtime/драйверов и
не заменяет hosted runner/VM. Сохранённые результаты GitHub Actions относятся к своим
revision/artifact hashes; этот документ не утверждает успешный прогон текущего HEAD.
Windows-контейнер не заменяет desktop installer/аппаратные испытания.

Фактические результаты добавляются в `verification-release.json`; `clean_vm=false`
сохраняется для локального прогона. Hosted Windows runner тоже не является пустой Windows:
для заявления о полноценной clean-machine совместимости нужна отдельная минимальная VM.

## Подтверждено локально 17 октября 2026

- 184 unit/API tests passed, 1 skipped (Windows symlink privilege), Ruff и pip check.
- ZIP: проверены 4386 файлов по manifest, запуск с PATH без Python, интерфейс/doctor,
  отсутствие модели с корректным unavailable, штатная остановка.
- Из отдельной распакованной копии обработан 20 s MP4 на CPU и Intel GPU через полный
  speech-only конвейер: по одному итоговому сегменту, валидные конечные времена.
- Контрольный 20 s WAV на bundled runtime: CPU load 0.828 s / ASR 2.172 s;
  GPU load 1.813 s / ASR 0.953 s; NPU static load 40.672 s / ASR 0.719 s.
  По три сегмента с валидными метками; SHA256 текста совпал на всех трёх устройствах.
  Это единичные функциональные пробы, а не сравнение производительности/точности.
- Отдельная сырая обрезанная 20 s запись без VAD дала невалидную метку в прямом probe;
  он завершился ошибкой, не выдумав конец. Полный MP4-конвейер с VAD проверен отдельно.

Первые проверки выявили подключение тестовой копии к рабочим CPU/GPU портам;
исправлено отдельными configurable loopback URL. Неисправные промежуточные прогоны
сохранены локально, но не засчитываются как прошедшие. Итоговые artifact hashes находятся
рядом с пакетами в `dist/SHA256SUMS.json`; проверка точного ZIP фиксирует hash в своём отчёте.

07.11.2026, 0.8.16: PrepareToInstall использует lifecycle helper из нового EXE, извлечённый в temp и запущенный встроенным Python целевой установки. Снимок PID/create_time/exe и список процессов создаются до подтверждения. Интерактивное «Да» разрешает завершение только этого снимка с повторной проверкой принадлежности executable каталогу установки и идентичности; новые/изменившиеся процессы блокируют замену. Проверка без согласия и silent setup ничего не останавливают. Обработка прерывается только после предупреждения о потере несохранённых правок. Внешние сервисы и произвольные деревья процессов не завершаются; uninstall сохраняет прежнюю блокировку. Проверки: tests/test_release_packaging.py и scripts/verify-installer-processes.py; последний использует только временные Windows-процессы, не рабочий NPU.
