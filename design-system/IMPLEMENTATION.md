# Реализация согласованной главной — этап 1

19.10.2026. Владелец согласовал направление и поручил выполнение в этом чате.

## Реализовано

- `scripts/build-ui-css.py` собирает общие `design-system/tokens.css`, `components.css` и `windows-app/ui/layout.css` в существующий `app.css`. `--check` проверяет синхронность. Новые frontend/runtime зависимости и HTTP routes не добавлены.
- Компактная главная, одна основная кнопка, постоянная навигация, отдельные области AI-настроек и диагностики. Все прежние формы, controls и 75 исходных ids сохранены.
- Hash-навигация сохраняет `?job=` и прочие query-параметры. Переходы и Back не стирают поля и выбранную запись. Skip link переводит фокус в текущую область.
- Единые кнопки, ссылки, поля, селекторы, media/WAV picker, статусы и progress. Папка модели по-прежнему выбирается через Windows API endpoint; отмена сохраняет путь.
- Upload показывает busy label, использует единую валидацию для выбора/drop, снимает busy/progress через loadend и проверяет readiness после ошибки. Неизвестный прогресс без value. Неизвестная метка конца отображается текстом.
- Таймкоды доступны с клавиатуры; неизменившиеся списки не заменяются при polling. При выборе другого задания старые generation/export actions скрываются до загрузки ответа.

Сервер, persisted job enums, payloads, instance headers, устройство, native postprocess и экспортные URLs не менялись. Общие assets редактора и WebView2 host прежние. Перенос `/create` и диалогов редактора — следующий этап.

## Проверки

| Проверка | Результат |
|---|---|
| `python scripts/check-ui-audit.py` | PASS: 79 исходных production файлов неизменны; 3 пути явно разрешены migration review; 75 исходных ids, 23 прежних назначения обработчиков и API literals сохранены. Всего 91 id и 83 прямых DOM targets. Baseline не перезаписывался. |
| `python scripts/build-ui-css.py --check`; `node --check windows-app/ui/app.js` | PASS |
| Ruff для трёх Python scripts; `git diff --check` | PASS |
| Backend/desktop tests | **85 passed**: test_desktop, test_first_run_setup, test_windows_runtime, test_device_policy, test_postprocess. Существующий venv, `-X utf8`. Первый запуск без UTF-8 дал mojibake в тесте кириллического пути; повтор в штатном UTF-8 режиме прошёл. Backend не менялся. |
| Настоящий production HTML/CSS/JS + fixture API | Пустой файл → inline error/focus; TXT → ошибка формата; WAV → raw File upload, 3244 bytes; прежние filename/title/mode/engine/device/speech_only/language, 202 и job selection. |
| Сеть при upload | Обрыв fixture connection → busy=false, progress скрыт, start disabled после 503 readiness. |
| Состояния | queued без value, running с processed/duration, error с retry, done с export/postprocess, no_speech с пустым текстом и сохранённым экспортом. `evidence/implementation/states.json`. |
| Обработчики | Retry → running; translate/notes → прежние folder/task + instance. Отмена папки сохраняет путь; inspect, custom WAV probe, diagnostics refresh, setup complete используют прежние endpoints. Journal: `evidence/implementation/requests.json`. |
| Редактор / экспорт | «Исправить» открывает прежний editSpeechReply с текстом/таймкодами. SRT/VTT/TXT/editor сохраняют URL/query. Реальное сохранение и экспорт данных в браузерном fixture не выполнялись. |
| Навигация | settings → diagnostics → Back сохраняет job/путь; setup complete → records сохраняет результат. Первый запуск без job открывает settings, явный job deep link не перекрывается мастером. |
| Размеры | 375×812, 760×560, 1024×768, 1200×820, 1440×900: горизонтального переполнения нет, readiness доступна. Метрики и JPEG: `evidence/implementation/`. |

Команда тестов из корня worktree:

```powershell
& 'E:/LocalAI/video desriptor/.venv-windows/Scripts/python.exe' -X utf8 -m pytest tests/test_desktop.py tests/test_first_run_setup.py tests/test_windows_runtime.py tests/test_device_policy.py tests/test_postprocess.py -q
```

## Безопасный просмотр

```powershell
python scripts/preview-ui.py --port 8948
```

Открыть `http://127.0.0.1:8948/?preview=ready`; результат: `/?preview=done&job=fixture-job`; первый запуск: `/?preview=setup`. Preview использует настоящие файлы UI, демонстрационные API, не запускает сервисы и не пишет workspace. Принимает только тестовые файлы до 2 МБ; production по-прежнему 4 ГБ. Реальные ключи не нужны. Request journal заменяет api_key на `[redacted]`.

## Границы

Рабочие Ollama/NPU/Sandbox не запускались, не останавливались и не менялись. Установленный EXE/installer не заменялись. Fixture проверяет обработчики и представление; это не аппаратный E2E и не Windows scaling/Narrator/high contrast приёмка. Контраст наследуется от проверенных токенов. Общий dialog shell и полная миграция редактора остаются этапами 3–4.

Откат — UI commits этой реализации; backend и пользовательские данные не мигрировали. Merge с веткой Sandbox не выполнялся.
