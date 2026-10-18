# Desktop preview 0.7 — Windows 11

Расширен существующий Windows launcher: небольшой WinForms EXE (.NET Framework,
встроенный в Windows) с Microsoft Edge WebView2. Python backend, HTTP API, HTML/CSS/JS,
устройства, модели, очередь и installer сохранены. Tauri 2 добавил бы Rust toolchain,
упаковку и новый supervisor без необходимости для этого среза. C# используется только
для окна, WebView и трея, backend не переписывается.

## Запуск и закрытие

Из установленного preview — **Video Descriptor** в Start Menu. Из ZIP —
**Open Video Descriptor.cmd**. Браузер/терминал/Docker для обычного запуска не нужны.
WebView2 Runtime должен быть уже установлен; при отсутствии показывается ошибка.
Runtime, драйверы и веса автоматически не устанавливаются.

По умолчанию используется прежний `windows-app/app.py`, порт 8780, встроенный Python
из ZIP либо `.venv-windows` для исходников. Окно сразу показывает состояние подключения.
`desktop.py` проверяет `/health`, подключается к своей установке или вызывает прежний
`app.py --no-browser`. Readiness ограничен 30 секундами; ошибка указывает логи и позволяет
повторить подключение. Timeout не убивает запускающийся backend. Python живёт независимо
от окна. Старые задания автоматически не возобновляются.

Идентичность требует app, desktop protocol 1, workspace, SHA256 расположения установки
и совпадения instance с локальным state-файлом. Любой HTTP 200, старый backend без
контракта и сервис на 8000 не считаются нашим приложением. Занятый/неотвечающий порт
даёт ошибку; неизвестный процесс не завершается. Старую версию нужно штатно закрыть.
Это защита от случайного подключения, не аутентификация против вредоносного локального
процесса с доступом к файлам пользователя.

Именованный mutex оставляет одно окно на установку; повторный запуск сигнализирует
ему восстановиться из трея. Backend сохраняет межпроцессный lock и получает exclusive
bind на Windows. Разные установки не присваивают один порт. Потеря backend обнаруживается
опросом раз в 2.5 сек.; WebView скрывается за экраном ошибки. Retry перепроверяет identity.

**Крестик всегда скрывает окно в трей**, даже при пустой очереди. Двойной щелчок по
значку/«Открыть» возвращает окно. «Завершить приложение» в трее вызывает прежний
защищённый stop API; queued/running задания дают отказ. Очередь не убивается. При потере
backend можно явно закрыть только окно/трей, оставив процессы нетронутыми. NPU/Ollama
оболочка не останавливает. Старая кнопка завершения в web UI останавливает HTTP backend;
оболочка затем показывает потерю соединения — для полного выхода используйте трей.

## Compose и безопасность

Compose CPU остаётся самостоятельным вариантом через `scripts/VideoDescriptor.ps1`.
Desktop 0.7 подключается только к нативному Windows backend; контейнерный UI в оболочке
в этот срез не входит. Docker не проверяется и не запускается при нативном запуске.
Контейнерный способ требует Docker Desktop с Linux Engine; диагностика остаётся
в прежнем launcher. Оболочка не выполняет docker stop/down и не перезапускает внешние сервисы.

WebView допускает только `http://127.0.0.1:<порт>`: верхняя/вложенная навигация,
новые окна и сетевые ресурсы ограничены этим origin. Внешние страницы не открываются.
Host objects, web messages, DevTools, browser shortcuts и дополнительные разрешения
отключены. Native JS bridge отсутствует. Экспорт использует стандартные downloads WebView2.
Localhost API проверяет Host, Origin (включая scheme) и Sec-Fetch-Site перед всеми
унаследованными/native endpoint; критические native действия сохраняют instance token.
HTTP слушает только loopback.

## Сборка и проверка

После прежней установки зависимостей для исходников:

```powershell
powershell -NoProfile -File windows-app/Prepare-Desktop.ps1
powershell -NoProfile -File windows-app/Start-App.ps1
# Прежние headless режимы сохранены:
powershell -NoProfile -File windows-app/Start-App.ps1 -NoBrowser
powershell -NoProfile -File windows-app/Start-App.ps1 -Doctor
# Реальное окно, отдельный workspace/порт, без загрузки моделей:
.venv-windows/Scripts/python.exe -X utf8 windows-app/verify_desktop.py
```

Prepare-Desktop получает закреплённый NuGet WebView2 SDK 1.0.2903.40, проверяет SHA256
из release-inputs.json, извлекает три DLL и LICENSE, компилирует EXE системным .NET compiler.
Системные компоненты не ставит. ZIP отказывает при устаревшем EXE относительно C# source/SDK;
payload/notices входят в hash manifest. Windows CI компилирует host, проверяет navigation
policy, реальное окно и прежний installer lifecycle. Container workflows не изменены.
CI не публикует Release. Повторяемость ZIP проверяется из одинаковых staged binaries;
побайтная воспроизводимость компиляции C# между машинами пока не заявляется.

На Windows host 18.10.2026 проверены EXE/WebView2, загрузка существующего DOM,
отказ stop при fixture active job, close-to-tray с сохранением backend, второй запуск
с восстановлением окна, экран потери backend и retry. GUI smoke использует отдельные
workspace/порты; fixture не доказывает ASR во время закрытия. UI также проверен визуально
через computer-use. Python-тесты запускают настоящий backend, конкурентные подключения,
чужие HTTP-сервисы, проверяют identity/Host/Origin и timeout без terminate.

Перед выпуском вручную пройти на чистой Windows 11: WebView2 отсутствует/установлен;
ярлыки после installer; импорт модели; длинное видео → крестик → повторное открытие →
готовый результат; экспорт через download dialog; расширенный редактор; размеры окна/DPI
и несколько мониторов; падение backend при настоящей обработке; upgrade/uninstall при
активном трее. Новая чистая VM, NPU/GPU ASR именно через оболочку, подпись EXE и поставка
WebView2 Runtime в этой итерации не подтверждены.
