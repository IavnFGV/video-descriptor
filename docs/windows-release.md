# Windows preview: ZIP, installer и CI

Текущая версия исходников пакета 0.5.0, Windows x64 / Windows 10+. Это частная проверочная сборка,
без цифровой подписи нашего EXE, выбранной лицензии проекта и готового публичного release.

## Состав и запуск

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

Данные новой установки лежат в `windows-app/runtime/` внутри её каталога. Installer не
включает этот каталог и `config.local.json` в свою таблицу устанавливаемых файлов.
Повторная установка/обновление и uninstall сохраняют данные/настройки. Удаление данных
не выполняется скрытым скриптом. Исторические материалы WSL/benchmark не импортируются.

Перед upgrade/uninstall нужно закрыть именно эту копию и её workers. Lifecycle check
проверяет процессы из её каталога и отказывает при занятости, не убивая процессы.
Внешние NPU/Ollama этим guard не останавливаются. Автоматического updater/rollback нет.

## Сборка

```powershell
$compiler = & ./windows-app/Prepare-BuildTools.ps1
./.venv-windows/Scripts/python.exe -X utf8 windows-app/build_release.py --iscc $compiler
```

Build tool устанавливается только в `windows-app/runtime/build-cache/inno-6.7.3` для
текущего пользователя. Скачать compiler/Python можно только по URL и SHA256 из
`release-inputs.json`; дополнительно проверяется Authenticode издателя Inno Setup.
Системные драйверы, Python и Docker не устанавливаются. Используемый compiler —
[Inno Setup 6.7.3](https://jrsoftware.org/isdl.php), runtime — официальный
[Python embeddable](https://docs.python.org/3.12/using/windows.html#windows-embeddable).

`requirements-release.txt` содержит точные версии без pytest/ruff. `release-wheels.json`
фиксирует имена и SHA256 46 wheel inputs. Сборка проверяет соответствие pins/metadata,
игнорирует старые посторонние wheel в cache и отказывается при checksum mismatch,
неоднозначном build, traversal или пересекающемся несовпадающем payload.
Обновление wheel lock возможно только отдельным явным `--refresh-lock` с review diff.

Результаты — `dist/VideoDescriptor-0.4.0-windows-x64.zip`, `*-setup.exe` и
`SHA256SUMS.json`. В каждом пакете `release-manifest.json` содержит hash/size каждого
файла и входных runtime/wheel. Notices/лицензии wheel сохранены в `.dist-info`.
Это inventory, не полный проверенный SPDX SBOM и не завершённый third-party legal bundle.
Особенно до публичного распространения нужно закрыть GPL/source obligations FFmpeg,
лицензию нашего кода, notices и подпись EXE; код и артефакты пока не публиковались.

ZIP использует сортировку файлов, фиксированные timestamp/permissions и одинаковый deflate.
Два запуска на одинаковых inputs должны дать одинаковые байты, что проверяется отдельно.
Это обещание воспроизводимости ZIP в закреплённом runtime; побитовая воспроизводимость
EXE и будущей Authenticode-подписи не заявлена. Manifest позволяет сравнить payload.

## Проверки

```powershell
./.venv-windows/Scripts/python.exe -X utf8 windows-app/verify_release.py `
  dist/VideoDescriptor-0.4.0-windows-x64.zip `
  --installer dist/VideoDescriptor-0.4.0-windows-x64-setup.exe `
  --iscc windows-app/runtime/build-cache/inno-6.7.3/ISCC.exe
```

Проверка создаёт отдельные временные каталоги с пробелами/кириллицей и реальные
тестовые установки. Проверяет hash файлов, запуск с PATH без Python, отсутствие модели,
loopback UI/doctor, graceful stop, запрет обновления работающей копии, reinstall,
upgrade fixture 0.4.0 → 0.4.1 и uninstall с сохранением sentinel/config.
Fixture меняет installer version, а не объявляет готовой версию приложения 0.4.1.
Тест не переустанавливает рабочую копию из `E:/LocalAI/video desriptor`.

Дополнительные `--video <short.mp4> --model <existing IR folder>` явно включают реальные
CPU/GPU ASR прогоны в распакованной копии на отдельных портах; по окончании завершаются
только workers этой копии с совпадением PID creation time и пути executable.
Веса не скачиваются. Это отдельная аппаратная проверка, не часть headless CI.

## CI и границы доказательств

Workflow `.github/workflows/windows-release.yml` на `windows-2025` выполняет unit/API
матрицу устройств, Ruff/pip check, сборку ZIP+EXE, повторную сборку ZIP, lifecycle checks
и сохраняет artifacts на 14 дней. Actions закреплены commit SHA, permissions — contents:read,
secrets/signing и публикация GitHub release не используются.

Локальный запуск на существующей Windows проверяет работу артефактов в отдельных каталогах.
Он не доказывает запуск на чистой Windows без установленных VC/runtime/драйверов и
не заменяет hosted runner/VM. Workflow ещё не выполнен на GitHub: для этого нужно отдельно
отправить коммиты; push в этой работе не выполняется. Docker daemon сейчас недоступен;
Windows-контейнер и без того не заменяет desktop installer/аппаратные испытания.

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
