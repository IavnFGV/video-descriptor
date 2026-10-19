# Проверки установленной Windows-сборки без ручных кликов

«Гость» здесь — вся временная Windows внутри Windows Sandbox. Её собственная
учётная запись WDAGUtilityAccount не является гостевой учётной записью ноутбука.
SAC Off и reboot относятся только к этой одноразовой системе.

## Что уже было в CI и что добавлено

До этого изменения Windows workflow собирал ZIP/EXE, проверял воспроизводимость,
install/reinstall/upgrade/uninstall, отказ обновления работающей копии, unit/API
контракты и настоящий WebView2 smoke. Реальный Whisper → Ollama → перевод/конспект
имел отдельный opt-in `verify_language_workflow.py`, работающий с распакованным ZIP,
но не был частью обычного CI.

Теперь `windows-app/verify_installed.py` устанавливает EXE в новый временный каталог,
сверяет версию и critical hashes с соответствующим ZIP и запускает проверки
**установленным Python**. Через реальный HTTP API он подключает проверенную модель,
готовит CPU, отправляет встроенный синтетический MP4 и проверяет непустой текст,
устройство, таймкоды и сохранённый job/result. Тест не использует mocks, host NPU
или частные пользовательские записи. После него завершаются только процессы этой
копии и выполняется её uninstall. В существующую зарегистрированную установку
этот verifier не устанавливает поверх.

Обычный `windows-release.yml` теперь запускает этот реальный CPU API smoke.
Публичная Whisper-модель закреплена revision/SHA256 и кэшируется; cache hit всё
равно проверяется по хешам, но не вызывает повторную загрузку 470 МиБ.

В ручном запуске workflow флаг `test_ollama=true` добавляет реальную генерацию,
перевод, конспект, chapters, HTML и экспорт SRT. Ollama устанавливается в отдельную
CI-папку из SHA256-pinned подписанного EXE; публичная тестовая модель хранится
отдельно. По умолчанию выбран `qwen3.5:0.8b`; это функциональный smoke, а не оценка
качества модели. Идентичность модели и версия сервиса попадают в отчёт.
Содержимое `inputs.ollama_model` передаётся через environment, а не вставляется
как исходный shell-код. Установки, модели и SAC основной Windows не используются.

На hosted CI runner Sandbox не нужна: тестируется свежая нативная установка
на Windows runner, без изменения защитной политики. Новые workflow-шаги пока
не объявляются выполненным GitHub Actions run: для этого нужны push и dispatch/PR.

## Команды

В чистой тестовой Windows или CI, где нет зарегистрированной пользовательской
установки:

```powershell
python -X utf8 windows-app/verify_installed.py `
  --installer dist/VideoDescriptor-0.7.0-windows-x64-setup.exe `
  --zip dist/VideoDescriptor-0.7.0-windows-x64.zip `
  --model C:\public-test-assets\whisper-small `
  --output dist/installed-acceptance/report.json
```

Для Ollama добавляются `--with-ollama --ollama-url http://127.0.0.1:11439
--ollama-model qwen3.5:0.8b`. Сервис и модель должны быть подготовлены отдельно;
`Prepare-TestOllama.ps1` устанавливает их только в CI/Sandbox, а на хосте допускает
только `-DownloadOnly`.

Одна команда с автоматическим созданием Sandbox и guest-only SAC Off, после
регистрации публичных test cache objects:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File windows-app/sandbox/Run-Acceptance.ps1 `
  -Profile Functional -GuestSacMode Off -Interaction Api -Stage notes `
  -OllamaModel qwen3.5:0.8b
```

`Api` — явная проверка backend/модели/результатов. `UI` — отдельный адаптер
WinForms/WebView2. API PASS не доказывает кнопки, диалоги, трей или UI-экспорт.

## Что воспроизведено локально

Итоговый чистый запуск `20261019-130555-850-functional` одной командой завершился
**PASS** за 381,204 с: preflight, установка EXE, backend API, CPU Whisper,
установка Ollama, обнаружение модели, генерация, перевод и конспект.
SAC изменён 1 → 0 только внутри Sandbox; одна перезагрузка сохранила guest ID,
а boot time изменился. Cleanup не выбран командой `-Stage notes`; отдельная
репетиция installed CI verifier проверила также uninstall тестовой копии.
См. [машинную сводку](installed-api-acceptance-evidence/summary.json),
[полный отчёт](installed-api-acceptance-evidence/functional-off-api/report.json),
[экспорт SRT](installed-api-acceptance-evidence/functional-off-api/translated.srt)
и [HTML конспекта](installed-api-acceptance-evidence/functional-off-api/notes-report.html).
Raw отчёты сохранены без исправлений. Их старые ссылки на PNG не означают
наличие UI-доказательств; API сохраняет JSON/результаты, и финальный bootstrap
уже убирает PNG из списка API evidence.

В настоящей Sandbox с установленным 0.7.0 подтверждены изменение гостевого SAC
1 → 0, единственный reboot и продолжение с тем же guest ID и новой boot time.
Основная Windows не менялась. В API-прогоне `20261019-123559-141-functional`
прошли preflight, установка, определение компонентов и реальный CPU Whisper:

- модель: официальный Whisper small FP16, digest
  `b5566bca9ac6075e6da66fda6d8a582b00ff59b5e9322376a0b400639aecd809`;
- OpenVINO/GenAI 2026.4.1; dynamic CPU, num_beams=1, word_timestamps=false;
- MP4 9.138005 с, один сегмент с корректными таймкодами;
- текст: `This is a local transcription test. The blue train arrives at the station at 9. Please save the sentence as subtitles.`

В последующем прогоне `20261019-125347-739-functional` подтверждены настоящая
установка Ollama 0.40.6, обнаружение публичной модели и реальная генерация.
Этот прогон целиком не объявляется PASS: его Whisper-проверка попала в гонку
снимка readiness, поэтому зависимые translation/notes были BLOCKED. Исправлен
именно polling verifier: теперь он ждёт положительной CPU readiness или конкретной
ошибки, а не одного `preparing=false`. Регрессионный тест фиксирует этот случай.

Первый CI-rehearsal выявил ошибку очистки verifier: список embedded Python включал
сам verifier. Это исправлено исключением собственного PID; отсутствие отчёта или
ошибка uninstall дают FAIL. Неудачные локальные попытки сохраняются, а не заменяются
результатом unit-тестов. Исправленный полный путь проверен отдельным прогоном
`ci-api-full`: PASS всех семи API-стадий, exit code 0 после удаления тестовой
установки. Это локальная репетиция того же CI entry point в Sandbox; запуск
GitHub Actions пока не выполнялся. Реальные отчёты, SRT и HTML сохранены в
[каталоге доказательств](installed-api-acceptance-evidence/ci-api-full/report.json).
Маленькая модель дала смешанный русский/английский перевод: тест проверяет
работоспособность цепочки и сохранение результатов, а не качество перевода.

Исторический Evaluation-only BLOCKED в [первом отчёте](verification-sandbox-harness.md)
сохранён. По последующему прямому разрешению владельца добавлен отдельный guest SAC
Off, а не переименован старый BLOCKED в PASS. Публичные модели/EXE не коммитятся.
[`sandbox.wsb`](../sandbox.wsb) сохраняется в Git как исходная ручная конфигурация;
[`Acceptance.template.wsb`](../windows-app/sandbox/Acceptance.template.wsb) — исходник
автоматически создаваемой конфигурации с LogonCommand и изолированными mappings.
